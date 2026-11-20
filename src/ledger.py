"""
The AR ledger as of any date: which invoices were open, how much was still owed,
how overdue they were, and whether a dispute was open.

Everything is computed from transactions dated on or before the as-of date, so
the same function serves history (to train and backtest the risk model) and today.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as cfg


@dataclass
class Ledger:
    customers: pd.DataFrame
    invoices: pd.DataFrame     # one row per invoice, with settle_date (NaT = not fully paid)
    payments: pd.DataFrame
    disputes: pd.DataFrame
    dunning: pd.DataFrame


def load() -> Ledger:
    cust = pd.read_csv(cfg.CUSTOMERS_CSV)
    inv = pd.read_csv(cfg.INVOICES_CSV, parse_dates=["invoice_date", "due_date"])
    pay = pd.read_csv(cfg.PAYMENTS_CSV, parse_dates=["payment_date"])
    disp = pd.read_csv(cfg.DISPUTES_CSV, parse_dates=["raised_date", "resolved_date"])
    dun = pd.read_csv(cfg.DUNNING_CSV, parse_dates=["activity_date", "promised_date"])
    return assemble(cust, inv, pay, disp, dun)


def assemble(cust, inv, pay, disp, dun) -> Ledger:
    """Derive settle dates and lateness from raw tables (also used for what-if ledgers)."""
    inv = inv[["invoice_id", "customer_id", "invoice_date", "due_date", "payment_terms_days",
               "amount"]].copy()
    pay = pay[["payment_id", "customer_id", "invoice_id", "payment_date", "amount"]].copy()

    # Settle date = the payment that brings the invoice to (near) zero.
    pay = pay.sort_values(["invoice_id", "payment_date"])
    pay["cum"] = pay.groupby("invoice_id")["amount"].cumsum()
    pay = pay.merge(inv[["invoice_id", "amount"]].rename(columns={"amount": "inv_amount"}), on="invoice_id")
    settled = pay[pay["cum"] >= pay["inv_amount"] - 0.01].groupby("invoice_id")["payment_date"].min()
    inv["settle_date"] = inv["invoice_id"].map(settled)
    inv["days_late"] = (inv["settle_date"] - inv["due_date"]).dt.days
    inv = inv.merge(cust[["customer_id", "segment", "billing_country"]], on="customer_id", how="left")
    return Ledger(cust, inv, pay.drop(columns=["cum", "inv_amount"]), disp, dun)


def open_items(led: Ledger, asof: pd.Timestamp) -> pd.DataFrame:
    """Invoices issued on/before `asof` and not fully paid by then, with open balance."""
    inv = led.invoices
    o = inv[(inv.invoice_date <= asof) & ~(inv.settle_date <= asof)].copy()
    paid = led.payments[led.payments.payment_date <= asof].groupby("invoice_id")["amount"].sum()
    o["paid_to_date"] = o["invoice_id"].map(paid).fillna(0.0)
    o["open_amount"] = (o["amount"] - o["paid_to_date"]).round(2)
    o = o[o.open_amount > 0.01]
    o["days_past_due"] = (asof - o["due_date"]).dt.days
    o["ageing_bucket"] = pd.cut(o["days_past_due"], cfg.AGEING_BINS, labels=cfg.AGEING_LABELS)
    d = led.disputes
    live = d[(d.raised_date <= asof) & ~(d.resolved_date <= asof)]
    o["dispute_open"] = o["invoice_id"].isin(live["invoice_id"]).astype(int)
    reason = live.drop_duplicates("invoice_id").set_index("invoice_id")["reason"]
    o["dispute_reason"] = o["invoice_id"].map(reason)
    o["partially_paid"] = (o["paid_to_date"] > 0).astype(int)
    return o.reset_index(drop=True)


def month_ends(start: pd.Timestamp, end: pd.Timestamp) -> list:
    return list(pd.date_range(start, end, freq="ME"))


def ageing_summary(o: pd.DataFrame) -> pd.DataFrame:
    s = o.groupby("ageing_bucket", observed=False).agg(invoices=("invoice_id", "count"),
                                                       open_usd=("open_amount", "sum"))
    s["share"] = s["open_usd"] / s["open_usd"].sum()
    return s


def weighted_mean(values, weights):
    w = np.asarray(weights, dtype=float)
    return float(np.average(values, weights=w)) if w.sum() > 0 else float("nan")
