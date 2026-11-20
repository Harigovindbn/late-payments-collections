"""
Late-payment risk score: a logistic regression, kept deliberately simple so a
credit controller can read every driver.

Backtest design (no peeking at the future):
  * At every month-end from mid-2024, take the open invoices and their features as
    known on that date, and record whether each was still unpaid 30 days after
    max(month-end, due date).
  * Walk forward through Jan-Sep 2026: at each month-end the model is retrained on
    every earlier row whose outcome was already known on that date (horizon <= month-end),
    then scores that month's open invoices. This is how it would run in production.
  * Compare, at a fixed collector capacity, how much of the money that really did
    go seriously late each prioritisation rule would have put in front of a collector:
      as-is   oldest item first (what the team does today)
      size    biggest overdue balance first
      risk    expected USD at risk = open amount x P(serious delay), summed per account
"""

import pickle

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config as cfg
from .features import FEATURES, add_target, build_features
from .ledger import Ledger, month_ends

MODEL_PATH = cfg.OUTPUT_DIR / "risk_model.pkl"


def build_panel(led: Ledger) -> pd.DataFrame:
    last = cfg.SNAPSHOT - pd.Timedelta(days=cfg.HORIZON_DAYS)
    frames = [add_target(build_features(led, me)) for me in month_ends(cfg.PANEL_START, last)]
    return pd.concat(frames, ignore_index=True)


def train(panel: pd.DataFrame, known_by: pd.Timestamp):
    """Fit on rows whose outcome was observable on `known_by`."""
    tr = panel[panel.horizon <= known_by]
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    model.fit(tr[FEATURES], tr["y"])
    return model


def walk_forward(panel: pd.DataFrame) -> pd.DataFrame:
    """Score each test month with a model trained only on what was known then."""
    scored = []
    for t in sorted(panel.loc[panel.as_of > cfg.TRAIN_END, "as_of"].unique()):
        model = train(panel, known_by=t)
        m = panel[panel.as_of == t].copy()
        m["p"] = model.predict_proba(m[FEATURES])[:, 1]
        scored.append(m)
    return pd.concat(scored, ignore_index=True)


def coefficients(model) -> pd.DataFrame:
    lr = model[-1]
    c = pd.DataFrame({"feature": FEATURES, "coef_per_sd": lr.coef_[0]})
    c["odds_ratio_per_sd"] = np.exp(c["coef_per_sd"])
    return c.reindex(c.coef_per_sd.abs().sort_values(ascending=False).index).round(3)


def account_view(rows: pd.DataFrame) -> pd.DataFrame:
    """Collectors work accounts, not invoices: roll invoices up per customer."""
    r = rows.assign(at_risk=rows.open_amount * rows.p,
                    overdue_usd=np.where(rows.days_past_due > 0, rows.open_amount, 0.0),
                    bad_usd=rows.open_amount * rows.y if "y" in rows else 0.0)
    return r.groupby(["as_of", "customer_id"]).agg(
        expected_at_risk=("at_risk", "sum"), oldest_dpd=("days_past_due", "max"),
        overdue_usd=("overdue_usd", "sum"), bad_usd=("bad_usd", "sum")).reset_index()


def capture_at_capacity(acc: pd.DataFrame, k: int) -> dict:
    """Share of seriously-late USD sitting in the top-k accounts, per rule, averaged over months."""
    rules = {"as-is: oldest first": "oldest_dpd", "biggest overdue first": "overdue_usd",
             "risk-based: expected USD at risk": "expected_at_risk"}
    out = {}
    for name, col in rules.items():
        shares = []
        for _, m in acc.groupby("as_of"):
            # only accounts a collector could act on: something overdue, or high risk
            m = m[(m.overdue_usd > 0) | (m.expected_at_risk > 0)]
            top = m.sort_values([col, "overdue_usd"], ascending=False).head(k)
            total = m.bad_usd.sum()
            if total > 0:
                shares.append(top.bad_usd.sum() / total)
        out[name] = float(np.mean(shares))
    return out


def evaluate(panel: pd.DataFrame) -> dict:
    te = walk_forward(panel)
    w = te.open_amount
    res = {"train_rows": int((panel.horizon <= cfg.TRAIN_END).sum()), "test_rows": len(te),
           "test_base_rate": float(te.y.mean()),
           "test_base_rate_usd": float((te.y * w).sum() / w.sum()),
           "auc": float(roc_auc_score(te.y, te.p)),
           "auc_usd_weighted": float(roc_auc_score(te.y, te.p, sample_weight=w)),
           "brier": float(brier_score_loss(te.y, te.p))}
    # baseline single-feature AUC: days past due alone (the as-is ageing view)
    res["auc_days_past_due_only"] = float(roc_auc_score(te.y, te.days_past_due))
    te["decile"] = pd.qcut(te.p.rank(method="first"), 10, labels=False) + 1
    cal = te.groupby("decile").agg(rows=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
    res["calibration"] = cal.round(3)
    acc = account_view(te)
    res["capacity"] = {k: capture_at_capacity(acc, k) for k in (20, cfg.COLLECTOR_CALLS_PER_WEEK, 60)}
    res["test_accounts_per_month"] = float(acc[(acc.overdue_usd > 0)].groupby("as_of").size().mean())
    res["scored_test"] = te
    return res


def fit_and_save(led: Ledger):
    """Backtest, then fit the production model on every outcome known today."""
    panel = build_panel(led)
    res = evaluate(panel)
    model = train(panel, known_by=cfg.SNAPSHOT)
    cfg.OUTPUT_DIR.mkdir(exist_ok=True)
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(model, fh)
    return model, panel, res


def write_report(res: dict, coefs: pd.DataFrame, path=None):
    path = path or cfg.OUTPUT_DIR / "risk_model_report.md"
    k = cfg.COLLECTOR_CALLS_PER_WEEK
    lines = ["# Late-payment risk score: backtest", "",
             f"Target: invoice still unpaid {cfg.HORIZON_DAYS} days after max(month-end, due date).",
             f"Trained on month-ends up to {cfg.TRAIN_END.date()} ({res['train_rows']:,} invoice-months); "
             f"tested on Jan-Sep 2026 ({res['test_rows']:,} invoice-months).", "",
             "| Metric | Value |", "| --- | ---: |",
             f"| Test base rate (invoices) | {res['test_base_rate']:.1%} |",
             f"| Test base rate (USD) | {res['test_base_rate_usd']:.1%} |",
             f"| AUC, risk score | **{res['auc']:.3f}** |",
             f"| AUC, USD-weighted | {res['auc_usd_weighted']:.3f} |",
             f"| AUC, days past due alone (as-is view) | {res['auc_days_past_due_only']:.3f} |",
             f"| Brier score | {res['brier']:.3f} |", "",
             f"## Which accounts reach a collector (avg {res['test_accounts_per_month']:.0f} accounts with overdue AR per month)", "",
             "Share of the USD that really went seriously late, sitting in the accounts each rule puts at the top of the list:", "",
             "| Rule | Top 20 | Top " + str(k) + " | Top 60 |", "| --- | ---: | ---: | ---: |"]
    for rule in res["capacity"][k]:
        lines.append(f"| {rule} | " + " | ".join(f"{res['capacity'][c][rule]:.1%}" for c in (20, k, 60)) + " |")
    lines += ["", "## Calibration (test set, by risk decile)", "", res["calibration"].to_markdown(), "",
              "## Drivers (standardised coefficients; odds ratio per +1 standard deviation)", "",
              coefs.to_markdown(index=False), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
