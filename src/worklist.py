"""
Today's collections worklist (as of config.SNAPSHOT).

Every open invoice is scored, rolled up to the account, and routed to ONE treatment.
Capacity is spent only where a human changes the outcome:

  1 Dispute desk            open dispute -> Billing fixes it first; dunning is paused
                            (chasing a disputed invoice annoys the customer and collects nothing)
  2 Escalate: credit hold   very high risk and oldest item 60+ days overdue -> stop new
                            orders, Finance Manager + Account Manager call; 120+ days -> agency/legal review
  3 Collector call          high risk and high USD at risk -> this week's call list,
                            ranked by expected USD at risk, capped at collector capacity
  4 Pre-due check           large invoice due soon from a risky account -> confirm it is
                            approved for payment before it becomes late
  5 Firm automated reminder high risk but low value, or anything 45+ days overdue
                            -> email + SMS sequence, no human time
  6 Standard reminder       everyone else: today's automated email ladder
"""

import pickle

import numpy as np
import pandas as pd

from . import config as cfg
from .features import FEATURES, REASON_TEXT, build_features
from .ledger import Ledger
from .risk_model import MODEL_PATH


def load_model():
    with open(MODEL_PATH, "rb") as fh:
        return pickle.load(fh)


def reason_codes(model, x: pd.DataFrame, top: int = 3) -> list:
    """Top drivers pushing each invoice's risk up: coefficient x standardised value."""
    scaler, lr = model[0], model[-1]
    z = (x[FEATURES].to_numpy(float) - scaler.mean_) / scaler.scale_
    contrib = z * lr.coef_[0]
    out = []
    for i, row in enumerate(contrib):
        r = x.iloc[i]
        texts = []
        for j in np.argsort(row)[::-1]:
            if row[j] <= 0.15 or len(texts) == top:
                break
            f = FEATURES[j]
            if f in ("days_to_due", "seg_enterprise", "seg_smb", "terms_days", "log_amount"):
                continue
            if r[f] == 0:   # "not in bucket X" or "no disputes" is not a reason to chase
                continue
            ctx = r.to_dict() | {"amount": r.open_amount, "dispute_reason": r.get("dispute_reason") or "?"}
            texts.append(REASON_TEXT[f].format(**ctx))
        out.append("; ".join(dict.fromkeys(texts)))
    return out


def score_open_items(led: Ledger, model=None, as_of=cfg.SNAPSHOT) -> pd.DataFrame:
    model = model or load_model()
    x = build_features(led, as_of)
    x["p_serious_delay"] = model.predict_proba(x[FEATURES])[:, 1]
    x["expected_at_risk"] = x["open_amount"] * x["p_serious_delay"]
    x["reasons"] = reason_codes(model, x)
    return x


def assign_treatment(a: pd.Series) -> str:
    if a.open_disputes > 0 and a.disputed_usd >= 0.5 * a.overdue_usd:
        return "1 Dispute desk"
    if a.risk >= cfg.VERY_HIGH_RISK and a.oldest_dpd >= cfg.CREDIT_HOLD_DPD:
        return "2 Escalate: credit hold" + (" + agency review" if a.oldest_dpd >= cfg.AGENCY_DPD else "")
    if a.risk >= cfg.HIGH_RISK and a.expected_at_risk >= cfg.HIGH_VALUE_USD:
        return "3 Collector call"
    if a.due_soon_usd >= cfg.PRE_DUE_MIN_USD and a.risk >= cfg.HIGH_RISK / 2:
        return "4 Pre-due check"
    if a.risk >= cfg.HIGH_RISK or a.oldest_dpd >= cfg.FIRM_REMINDER_DPD:
        return "5 Firm automated reminder"
    return "6 Standard reminder"


def build_worklist(led: Ledger, model=None, as_of=cfg.SNAPSHOT):
    x = score_open_items(led, model, as_of)
    return accounts_from_scored(x, led.customers)


def accounts_from_scored(x: pd.DataFrame, customers: pd.DataFrame):
    """Roll scored open invoices (needs p_serious_delay, expected_at_risk, reasons) up to
    accounts and assign treatments. Used for today's list and for the month-by-month replay."""
    due_soon = x.days_past_due.between(-cfg.PRE_DUE_WINDOW_DAYS, 0)
    x = x.assign(overdue=np.where(x.days_past_due > 0, x.open_amount, 0.0),
                 disputed=np.where(x.dispute_open == 1, x.open_amount, 0.0),
                 due_soon=np.where(due_soon, x.open_amount, 0.0))
    top_reason = (x.sort_values("expected_at_risk", ascending=False)
                  .groupby("customer_id")["reasons"].first())
    acc = x.groupby("customer_id").agg(
        open_invoices=("invoice_id", "count"), open_ar=("open_amount", "sum"),
        overdue_usd=("overdue", "sum"), disputed_usd=("disputed", "sum"),
        open_disputes=("dispute_open", "sum"), due_soon_usd=("due_soon", "sum"),
        oldest_dpd=("days_past_due", "max"), expected_at_risk=("expected_at_risk", "sum"))
    acc["risk"] = acc.expected_at_risk / acc.open_ar          # USD-weighted P(serious delay)
    acc["why"] = top_reason
    acc = acc.join(customers.set_index("customer_id")[["name", "segment", "billing_country",
                                                           "payment_terms_days", "credit_limit"]])
    acc["treatment"] = acc.apply(assign_treatment, axis=1)

    # Collector capacity: the call list is ranked by expected USD at risk; overflow waits a week.
    acc = acc.sort_values("expected_at_risk", ascending=False)
    calls = acc.treatment == "3 Collector call"
    acc["call_rank"] = np.where(calls, calls.cumsum(), 0)
    acc["call_week"] = np.where(calls, (acc.call_rank - 1) // cfg.COLLECTOR_CALLS_PER_WEEK + 1, 0)
    acc = acc.reset_index()
    acc["priority_rank"] = acc.index + 1
    cols = ["priority_rank", "customer_id", "name", "segment", "billing_country", "treatment",
            "call_week", "open_ar", "overdue_usd", "disputed_usd", "oldest_dpd", "risk",
            "expected_at_risk", "credit_limit", "payment_terms_days", "open_invoices", "why"]
    acc = acc[cols].round({"open_ar": 2, "overdue_usd": 2, "disputed_usd": 2, "risk": 3,
                           "expected_at_risk": 2})
    inv_cols = ["invoice_id", "customer_id", "invoice_date", "due_date", "amount", "open_amount",
                "days_past_due", "ageing_bucket", "dispute_open", "dispute_reason",
                "p_serious_delay", "expected_at_risk", "reasons"]
    items = x[inv_cols].sort_values("expected_at_risk", ascending=False).round(
        {"p_serious_delay": 3, "expected_at_risk": 2})
    return acc, items


def treatment_summary(acc: pd.DataFrame) -> pd.DataFrame:
    s = acc.groupby("treatment").agg(accounts=("customer_id", "count"), open_ar=("open_ar", "sum"),
                                     overdue_usd=("overdue_usd", "sum"),
                                     expected_at_risk=("expected_at_risk", "sum"))
    s["share_of_risk"] = s.expected_at_risk / s.expected_at_risk.sum()
    return s.round(2)
