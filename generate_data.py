"""
Late Payments & Collections - synthetic accounts-receivable generator.

Continues the contract-to-cash story of the Revenue Leakage Detector: it takes the
same 300 customers and the same invoices (data/source/, copied from that project)
and adds what happens AFTER the invoice is sent:

  data/customers.csv      customer master + payment terms + credit limit
  data/invoices.csv       invoice headers (one row per invoice, gross USD, due date)
  data/payments.csv       cash received, applied to invoices (some partial payments)
  data/disputes.csv       invoices the customer queried, with reason and resolution date
  data/dunning_log.csv    collections activity under today's (as-is) policy:
                          reminders by age, collector calls, promises to pay

Answer key (never read by the analysis, used only to sanity-check it):
  data/truth_customer_behaviour.csv   hidden payment persona per customer

The link to project 1: invoices that carry a billing error (data/source/planted_leaks.csv)
are much more likely to be disputed, and a disputed invoice is paid weeks later.

Usage:  python generate_data.py [--seed 7]
"""

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "data" / "source"
OUT = ROOT / "data"

SNAPSHOT = date(2026, 10, 31)      # "today": the AR ledger is viewed as of this date

TERMS_BY_SEGMENT = {               # payment terms (days) and their probability
    "Enterprise": ([60, 45, 30], [0.55, 0.30, 0.15]),
    "Mid-market": ([45, 30], [0.40, 0.60]),
    "SMB": ([30, 15], [0.85, 0.15]),
}
PERSONAS = {                       # hidden behaviour, share of customers
    "prompt": 0.35,                # pays on or near the due date
    "steady_late": 0.27,           # always 1-3 weeks late, predictable
    "slow": 0.14,                  # stretches payables, 3-6 weeks late
    "admin_chaos": 0.10,           # usually fine, sometimes very late (lost invoice, no PO)
    "deteriorating": 0.14,         # was fine, getting later every month (cash stress)
}
P_DEFAULT_GIVEN_DETERIORATING = 0.45

P_DISPUTE_OVERBILLED = 0.65        # customer notices it was over-charged
P_DISPUTE_BILLING_ERROR = 0.18     # any other billing error: AP rejects the PO mismatch
P_DISPUTE_OTHER = 0.025            # PO missing, service issue, wrong contact
OTHER_DISPUTE_REASONS = ["PO number missing", "Service issue", "Wrong billing contact"]

TAX_TO_COUNTRY = {0.05: "AE", 0.10: "AU", 0.15: "NZ", 0.19: "DE", 0.21: "NL", 0.23: "IE"}


def month_index(d: date) -> int:
    return d.year * 12 + d.month


def to_weekday(d: date) -> date:
    """Cash arrives on business days."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def build_ledger():
    lines = pd.read_csv(SRC / "invoices.csv")
    cmap = pd.read_csv(SRC / "invoice_contract_map.csv")[["invoice_line_id", "customer_id"]]
    cust = pd.read_csv(SRC / "customers.csv")
    lines = lines.merge(cmap, on="invoice_line_id", how="left")
    lines["gross"] = lines["net_amount"] + lines["tax_amount"]

    # Invoices whose customer is not in the master (project 1's "no contract" lines) are
    # one-off accounts in the billing system. Give each a C9xxx account.
    orphan_names = sorted(lines.loc[lines.customer_id.isna(), "customer_name"].unique())
    orphan_ids = {n: f"C9{k:03d}" for k, n in enumerate(orphan_names, start=1)}
    mask = lines.customer_id.isna()
    lines.loc[mask, "customer_id"] = lines.loc[mask, "customer_name"].map(orphan_ids)
    orphan_rows = (lines[mask].groupby("customer_id")
                   .agg(name=("customer_name", "first"), tax=("tax_rate", "first")).reset_index())
    orphan_rows["billing_country"] = orphan_rows["tax"].round(2).map(TAX_TO_COUNTRY)
    orphan_rows["segment"] = "SMB"
    cust = pd.concat([cust, orphan_rows[["customer_id", "name", "billing_country", "segment"]]],
                     ignore_index=True)

    inv = (lines.groupby("invoice_id")
           .agg(customer_id=("customer_id", "first"), invoice_date=("invoice_date", "first"),
                amount=("gross", "sum"))
           .reset_index())
    inv["amount"] = inv["amount"].round(2)
    inv["invoice_date"] = pd.to_datetime(inv["invoice_date"]).dt.date
    return inv, cust


def billing_error_flags(inv):
    leaks = pd.read_csv(SRC / "planted_leaks.csv")
    over = set(leaks.loc[leaks.billed_amount > leaks.expected_amount, "invoice_id"])
    anyerr = set(leaks["invoice_id"])
    return over, anyerr


def draw_days_late(persona, c, inv_date, rng):
    """Natural lateness (payment date minus due date) for one invoice, in days."""
    if persona == "prompt":
        d = rng.gauss(-1, 3)
        if rng.random() < 0.07:
            d = rng.uniform(8, 25)
    elif persona == "steady_late":
        d = rng.gauss(13, 5)
    elif persona == "slow":
        d = rng.gauss(33, 9)
    elif persona == "admin_chaos":
        d = rng.gauss(2, 4) if rng.random() < 0.62 else rng.uniform(20, 75)
    else:  # deteriorating
        base = rng.gauss(c["base_late"], 4)
        months = month_index(inv_date) - month_index(c["deteriorate_start"])
        d = base + max(0, months) * rng.uniform(5, 9)
    return d + c["offset"]


def main(seed: int):
    rng = random.Random(seed)
    np.random.seed(seed)
    inv, cust = build_ledger()
    over_billed, has_error = billing_error_flags(inv)

    # ---------------- customer master + hidden behaviour -----------------
    names, weights = zip(*PERSONAS.items())
    rows, truth = [], []
    monthly = inv.assign(m=inv.invoice_date.map(month_index)).groupby("customer_id").amount.sum()
    months_active = inv.assign(m=inv.invoice_date.map(month_index)).groupby("customer_id").m.nunique()
    for _, r in cust.iterrows():
        cid = r.customer_id
        terms_opts, terms_p = TERMS_BY_SEGMENT[r.segment]
        terms = rng.choices(terms_opts, terms_p)[0]
        persona = rng.choices(names, weights)[0]
        c = {"persona": persona, "offset": rng.gauss(0, 2.5) + (3 if r.segment == "Enterprise" else 0),
             "base_late": rng.choice([-1, 2, 6]), "deteriorate_start": None, "default_month": None}
        if persona == "deteriorating":
            start = date(2025, rng.randint(7, 12), 1) if rng.random() < 0.5 else date(2026, rng.randint(1, 5), 1)
            c["deteriorate_start"] = start
            if rng.random() < P_DEFAULT_GIVEN_DETERIORATING:
                m = month_index(start) + rng.randint(4, 7)
                y, mo = divmod(m - 1, 12)
                c["default_month"] = date(y, mo + 1, 1)
        avg_month = monthly.get(cid, 0) / max(months_active.get(cid, 1), 1)
        credit_limit = max(5000, round(avg_month * (terms / 30 + 1) * 1.25, -3))
        rows.append({"customer_id": cid, "name": r["name"], "billing_country": r.billing_country,
                     "segment": r.segment, "payment_terms_days": terms, "credit_limit": credit_limit})
        truth.append({"customer_id": cid, "persona": persona,
                      "deteriorate_start": c["deteriorate_start"], "default_month": c["default_month"]})
        rows[-1]["_c"] = c
    customers = pd.DataFrame(rows)
    cinfo = {r["customer_id"]: r["_c"] for r in rows}
    terms_map = customers.set_index("customer_id")["payment_terms_days"]

    inv["payment_terms_days"] = inv.customer_id.map(terms_map)
    inv["due_date"] = [d + timedelta(days=int(t)) for d, t in zip(inv.invoice_date, inv.payment_terms_days)]
    inv = inv.sort_values(["invoice_date", "invoice_id"]).reset_index(drop=True)

    payments, disputes, dunning = [], [], []
    pay_no = disp_no = act_no = 0

    for _, r in inv.iterrows():
        c = cinfo[r.customer_id]
        due = r.due_date
        days_late = draw_days_late(c["persona"], c, r.invoice_date, rng)
        never_pays = c["default_month"] is not None and r.invoice_date >= c["default_month"] - timedelta(days=62)

        # ---- disputes: billing errors from project 1 drive most of them ----
        p_disp = P_DISPUTE_OTHER
        reason = rng.choice(OTHER_DISPUTE_REASONS)
        if r.invoice_id in over_billed:
            p_disp, reason = P_DISPUTE_OVERBILLED, "Over-charged (tax rate)"
        elif r.invoice_id in has_error:
            p_disp, reason = P_DISPUTE_BILLING_ERROR, "Amount does not match PO"
        resolved = None
        if rng.random() < p_disp:
            raised = r.invoice_date + timedelta(days=rng.randint(5, int(r.payment_terms_days) + 10))
            resolved = raised + timedelta(days=int(rng.gauss(35, 12)) if reason != "Wrong billing contact" else rng.randint(5, 15))
            resolved = max(resolved, raised + timedelta(days=3))
            disp_no += 1
            disputes.append({"dispute_id": f"D{disp_no:05d}", "invoice_id": r.invoice_id,
                             "customer_id": r.customer_id, "raised_date": raised, "reason": reason,
                             "resolved_date": resolved if resolved <= SNAPSHOT else None,
                             "status": "Resolved" if resolved <= SNAPSHOT else "Open"})
            if raised > SNAPSHOT:   # not yet raised as of today
                disputes.pop(); disp_no -= 1; resolved = None

        pay_date = due + timedelta(days=round(days_late))
        if resolved is not None:
            pay_date = max(pay_date, resolved + timedelta(days=rng.randint(3, 12)))
        pay_date = to_weekday(max(pay_date, r.invoice_date + timedelta(days=3)))
        if never_pays:
            pay_date = None

        # ---- payments (some customers pay part first) ----
        if pay_date is not None and pay_date <= SNAPSHOT:
            p_partial = 0.12 if c["persona"] in ("slow", "deteriorating") else 0.04
            if rng.random() < p_partial and (pay_date - due).days > 0:
                first = to_weekday(due + timedelta(days=rng.randint(0, max(1, (pay_date - due).days))))
                share = round(rng.uniform(0.4, 0.8), 2)
                part = round(r.amount * share, 2)
                pay_no += 1
                payments.append({"payment_id": f"P{pay_no:06d}", "customer_id": r.customer_id,
                                 "invoice_id": r.invoice_id, "payment_date": first, "amount": part})
                pay_no += 1
                payments.append({"payment_id": f"P{pay_no:06d}", "customer_id": r.customer_id,
                                 "invoice_id": r.invoice_id, "payment_date": pay_date,
                                 "amount": round(r.amount - part, 2)})
            else:
                pay_no += 1
                payments.append({"payment_id": f"P{pay_no:06d}", "customer_id": r.customer_id,
                                 "invoice_id": r.invoice_id, "payment_date": pay_date, "amount": r.amount})
        elif pay_date is not None and rng.random() < 0.05 and pay_date > SNAPSHOT and due < SNAPSHOT:
            # an occasional partial payment already received on a still-open invoice
            part_date = to_weekday(due + timedelta(days=rng.randint(1, 20)))
            if part_date <= SNAPSHOT:
                pay_no += 1
                payments.append({"payment_id": f"P{pay_no:06d}", "customer_id": r.customer_id,
                                 "invoice_id": r.invoice_id, "payment_date": part_date,
                                 "amount": round(r.amount * rng.uniform(0.3, 0.6), 2)})

        # ---- as-is dunning: same ladder for everyone, driven only by age ----
        settled = pay_date if pay_date is not None else date.max
        ladder = [(1, "Email", "Reminder 1"), (14, "Email", "Reminder 2"),
                  (30, "Call", "Collector call"), (45, "Email", "Final notice"),
                  (60, "Call", "Escalation call")]
        for offset, channel, step in ladder:
            when = to_weekday(due + timedelta(days=offset))
            if when >= settled or when > SNAPSHOT:
                break
            # as-is: collectors work oldest-first and run out of time; ~40% of calls never happen
            if channel == "Call" and rng.random() < 0.40:
                continue
            outcome, promise = "Sent", None
            if channel == "Call":
                roll = rng.random()
                if roll < 0.35:
                    outcome = "No answer"
                elif resolved is not None and when < resolved:
                    outcome = "Customer cites dispute"
                else:
                    outcome = "Promise to pay"
                    promise = to_weekday(when + timedelta(days=rng.randint(5, 14)))
            act_no += 1
            kept = None
            if promise is not None and promise + timedelta(days=3) <= SNAPSHOT:
                kept = settled <= promise + timedelta(days=3)
            dunning.append({"activity_id": f"A{act_no:06d}", "invoice_id": r.invoice_id,
                            "customer_id": r.customer_id, "activity_date": when, "channel": channel,
                            "step": step, "outcome": outcome, "promised_date": promise,
                            "promise_kept": kept})

    customers = customers.drop(columns="_c")
    OUT.mkdir(exist_ok=True)
    customers.to_csv(OUT / "customers.csv", index=False)
    inv[["invoice_id", "customer_id", "invoice_date", "due_date", "payment_terms_days", "amount"]] \
        .to_csv(OUT / "invoices.csv", index=False)
    pd.DataFrame(payments).sort_values(["payment_date", "payment_id"]).to_csv(OUT / "payments.csv", index=False)
    pd.DataFrame(disputes).to_csv(OUT / "disputes.csv", index=False)
    pd.DataFrame(dunning).to_csv(OUT / "dunning_log.csv", index=False)
    pd.DataFrame(truth).to_csv(OUT / "truth_customer_behaviour.csv", index=False)

    print(f"customers {len(customers)} | invoices {len(inv)} (USD {inv.amount.sum()/1e6:.1f}M) | "
          f"payments {len(payments)} | disputes {len(disputes)} | dunning actions {len(dunning)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    main(ap.parse_args().seed)
