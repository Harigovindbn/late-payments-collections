"""
Collections KPIs, month by month:

  DSO      days sales outstanding      = open AR / billing in last 90 days x 90
  BPDSO    best possible DSO           = current (not yet due) AR / billing x 90
  ADD      average days delinquent     = DSO - BPDSO  (the part collections can fix)
  CEI      collection effectiveness    = (opening AR + billing - closing AR)
                                         / (opening AR + billing - closing current AR)
  % 90+    share of AR more than 90 days past due
"""

import pandas as pd

from . import config as cfg
from .ledger import Ledger, month_ends, open_items


def monthly_kpis(led: Ledger, start=pd.Timestamp("2024-03-31"), end=cfg.SNAPSHOT) -> pd.DataFrame:
    rows, prev_ar = [], None
    inv = led.invoices
    for me in month_ends(start, end):
        o = open_items(led, me)
        ar = o.open_amount.sum()
        current = o.loc[o.days_past_due <= 0, "open_amount"].sum()
        overdue90 = o.loc[o.days_past_due > 90, "open_amount"].sum()
        # Invoices are dated the 1st, so use the last three calendar months of billing
        # (a rolling 90-day window would sometimes catch only two billing runs).
        start3 = me - pd.offsets.MonthEnd(3)
        billed_3m = inv.loc[(inv.invoice_date > start3) & (inv.invoice_date <= me), "amount"].sum()
        days_3m = (me - start3).days
        billed_m = inv.loc[(inv.invoice_date > me - pd.offsets.MonthEnd(1)) & (inv.invoice_date <= me), "amount"].sum()
        dso = ar / billed_3m * days_3m
        bpdso = current / billed_3m * days_3m
        cei = None
        if prev_ar is not None:
            cei = (prev_ar + billed_m - ar) / (prev_ar + billed_m - current) * 100
        rows.append({"month_end": me.date(), "open_ar": round(ar, 2), "current_ar": round(current, 2),
                     "overdue_ar": round(ar - current, 2), "ar_90_plus": round(overdue90, 2),
                     "billed_month": round(billed_m, 2), "dso": round(dso, 1), "bpdso": round(bpdso, 1),
                     "add": round(dso - bpdso, 1), "cei": None if cei is None else round(cei, 1),
                     "pct_90_plus": round(overdue90 / ar * 100, 1) if ar else 0.0,
                     "open_disputes_usd": round(o.loc[o.dispute_open == 1, "open_amount"].sum(), 2)})
        prev_ar = ar
    return pd.DataFrame(rows)


def dispute_impact(led: Ledger) -> pd.DataFrame:
    """How much later disputed invoices are paid, by dispute reason (paid invoices only)."""
    inv = led.invoices[led.invoices.settle_date.notna()].copy()
    first = led.disputes.drop_duplicates("invoice_id").set_index("invoice_id")["reason"]
    inv["reason"] = inv["invoice_id"].map(first).fillna("No dispute")
    g = inv.groupby("reason").agg(invoices=("invoice_id", "count"), usd=("amount", "sum"),
                                  avg_days_late=("days_late", "mean"),
                                  median_days_late=("days_late", "median"))
    return g.sort_values("usd", ascending=False).round(1)
