"""
Features for the late-payment risk score, computed as of a date using ONLY what
was known on that date (payments, disputes and promises dated on or before it).

Invoice level:   days past due, amount, open dispute, part-paid, payment terms
Customer level:  how late they paid over the last 12 months, whether that is getting
                 worse, broken promises to pay, how much of their balance is overdue,
                 their oldest overdue item, credit-limit usage
"""

import numpy as np
import pandas as pd

from . import config as cfg
from .ledger import Ledger, open_items

FEATURES = [
    # Age enters as buckets, not a straight line: in a linear term "older" can only ever
    # mean "more likely" or "less likely" to be paid, and the truth is neither.
    "days_to_due", "dpd_1_30", "dpd_31_60", "dpd_61_90", "dpd_90_plus",
    "log_amount", "dispute_open", "partially_paid", "terms_days",
    "cust_avg_days_late", "cust_late30_share", "cust_trend", "cust_no_history",
    "cust_overdue_share", "cust_max_dpd", "cust_broken_promises", "cust_disputes_12m",
    "cust_credit_usage", "seg_enterprise", "seg_smb",
]

# Plain-English templates for the reason codes collectors see on the worklist
REASON_TEXT = {
    "dpd_1_30": "{days_past_due:.0f} days past due",
    "dpd_31_60": "{days_past_due:.0f} days past due",
    "dpd_61_90": "{days_past_due:.0f} days past due",
    "dpd_90_plus": "{days_past_due:.0f} days past due",
    "log_amount": "large invoice (USD {amount:,.0f})",
    "dispute_open": "open dispute: {dispute_reason}",
    "partially_paid": "part-paid only",
    "cust_avg_days_late": "usually pays {cust_avg_days_late:.0f} days late",
    "cust_late30_share": "{cust_late30_share:.0%} of invoices paid 30+ days late",
    "cust_trend": "paying {cust_trend:.0f} days later than a year ago",
    "cust_no_history": "new / one-off account, no payment history",
    "cust_overdue_share": "{cust_overdue_share:.0%} of balance overdue",
    "cust_max_dpd": "oldest item {cust_max_dpd:.0f} days overdue",
    "cust_broken_promises": "{cust_broken_promises:.0f} broken promise(s) to pay",
    "cust_disputes_12m": "{cust_disputes_12m:.0f} dispute(s) in 12 months",
    "cust_credit_usage": "at {cust_credit_usage:.0%} of credit limit",
    "terms_days": "{terms_days:.0f}-day terms",
    "days_to_due": "not yet due",
    "seg_enterprise": "enterprise account",
    "seg_smb": "SMB account",
}


def customer_features(led: Ledger, as_of: pd.Timestamp, o: pd.DataFrame) -> pd.DataFrame:
    inv = led.invoices
    lo = as_of - pd.Timedelta(days=cfg.LOOKBACK_DAYS)
    paid = inv[(inv.settle_date > lo) & (inv.settle_date <= as_of)]
    g = paid.groupby("customer_id")["days_late"]
    f = pd.DataFrame({"cust_avg_days_late": g.mean(),
                      "cust_late30_share": g.apply(lambda s: (s > 30).mean()),
                      "cust_n_paid": g.size()})
    recent = paid[paid.settle_date > as_of - pd.Timedelta(days=cfg.RECENT_DAYS)]
    f["cust_recent_late"] = recent.groupby("customer_id")["days_late"].mean()
    # Open items count too: an invoice still unpaid at 80 days is at least 80 days late.
    unpaid_late = o[o.days_past_due > 0].groupby("customer_id")["days_past_due"].max()
    f = f.reindex(f.index.union(o.customer_id.unique()))
    f["cust_recent_late"] = np.fmax(f["cust_recent_late"], unpaid_late.reindex(f.index))
    f["cust_trend"] = (f["cust_recent_late"] - f["cust_avg_days_late"]).clip(-30, 120)

    tot = o.groupby("customer_id")["open_amount"].sum()
    overdue = o[o.days_past_due > 0].groupby("customer_id")["open_amount"].sum()
    f["cust_overdue_share"] = (overdue.reindex(f.index).fillna(0) / tot.reindex(f.index)).fillna(0)
    f["cust_max_dpd"] = o.groupby("customer_id")["days_past_due"].max().reindex(f.index).clip(lower=0).fillna(0)
    lim = led.customers.set_index("customer_id")["credit_limit"]
    f["cust_credit_usage"] = (tot.reindex(f.index).fillna(0) / lim.reindex(f.index)).fillna(0).clip(0, 5)

    # Broken promises: the promised date (+3 days grace) has passed and the invoice was not settled.
    d = led.dunning
    pr = d[d.promised_date.notna() & (d.promised_date > lo) & (d.promised_date + pd.Timedelta(days=3) <= as_of)]
    pr = pr.merge(inv[["invoice_id", "settle_date"]], on="invoice_id", how="left")
    broken = pr[~(pr.settle_date <= pr.promised_date + pd.Timedelta(days=3))]
    f["cust_broken_promises"] = broken.groupby("customer_id").size().reindex(f.index).fillna(0)
    ds = led.disputes
    f["cust_disputes_12m"] = (ds[(ds.raised_date > lo) & (ds.raised_date <= as_of)]
                              .groupby("customer_id").size().reindex(f.index).fillna(0))

    f["cust_no_history"] = (f["cust_n_paid"].fillna(0) < 3).astype(int)
    for col in ["cust_avg_days_late", "cust_late30_share", "cust_trend"]:
        f[col] = f[col].fillna(0.0)
    return f.drop(columns=["cust_n_paid", "cust_recent_late"])


def build_features(led: Ledger, as_of: pd.Timestamp) -> pd.DataFrame:
    """One row per open invoice as of `as_of`, with all model features."""
    o = open_items(led, as_of)
    if o.empty:
        return o
    f = customer_features(led, as_of, o)
    x = o.merge(f, left_on="customer_id", right_index=True, how="left")
    x["as_of"] = as_of
    x["terms_days"] = x["payment_terms_days"]
    x["days_to_due"] = (-x["days_past_due"]).clip(lower=0)
    dpd = x["days_past_due"]
    x["dpd_1_30"] = dpd.between(1, 30).astype(int)
    x["dpd_31_60"] = dpd.between(31, 60).astype(int)
    x["dpd_61_90"] = dpd.between(61, 90).astype(int)
    x["dpd_90_plus"] = (dpd > 90).astype(int)
    x["cust_max_dpd"] = x["cust_max_dpd"].clip(upper=180)
    x["log_amount"] = np.log1p(x["open_amount"])
    x["seg_enterprise"] = (x["segment"] == "Enterprise").astype(int)
    x["seg_smb"] = (x["segment"] == "SMB").astype(int)
    return x


def add_target(x: pd.DataFrame) -> pd.DataFrame:
    """y = 1 if still unpaid HORIZON_DAYS after max(as-of date, due date). Rows whose
    horizon is after the snapshot have no known outcome and are dropped."""
    horizon = np.maximum(x["as_of"], x["due_date"]) + pd.Timedelta(days=cfg.HORIZON_DAYS)
    x = x.assign(horizon=horizon)
    x = x[x.horizon <= cfg.SNAPSHOT].copy()
    x["y"] = (~(x["settle_date"] <= x["horizon"])).astype(int)
    return x
