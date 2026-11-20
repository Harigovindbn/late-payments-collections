"""
Cash-flow impact: what would Jan-Oct 2026 have looked like under the risk-based strategy?

Method (a replay, not a forecast):
  1. At every month-end Jan-Sep 2026, score the open invoices with a model trained only on
     outcomes known that day, roll up to accounts and assign the to-be treatment - exactly
     what the worklist would have said then. Collector calls are capped at capacity.
  2. Apply the treatment effects in config.SCENARIOS to the invoices those accounts had open:
        collector call / firm reminder / pre-due check  -> cut the invoice's lateness by x%
        dispute desk                                     -> cut the remaining dispute time by x%
        credit hold                                      -> no new invoices to a held account
                                                            that it then never paid (exposure avoided)
        escalation / agency                              -> recover x% of the held account's
                                                            unpaid overdue balance, 60 days later
     No treatment can make an invoice pay before the action date + 3 days.
  3. Rebuild the ledger with the shifted payments and recompute every KPI.

What the replay cannot know: invoices that were still open at the snapshot have no actual
pay date to improve on, so they get no timing benefit (conservative).
"""

import numpy as np
import pandas as pd

from . import config as cfg
from . import kpis
from .features import FEATURES, build_features
from .ledger import Ledger, assemble, month_ends, open_items
from .risk_model import build_panel, train
from .worklist import accounts_from_scored

LEVERS = ["call", "firm_reminder", "pre_due", "dispute_desk", "credit_hold", "recovery"]
TREATMENT_LEVER = {"3 Collector call": "call", "5 Firm automated reminder": "firm_reminder",
                   "4 Pre-due check": "pre_due", "1 Dispute desk": "dispute_desk"}
BILLING_ERROR_REASONS = ["Amount does not match PO", "Over-charged (tax rate)"]
DAY = pd.Timedelta(days=1)


# --------------------------------------------------------------------------
# 1. What the to-be worklist would have said each month
# --------------------------------------------------------------------------
def treatment_history(led: Ledger, panel=None):
    panel = build_panel(led) if panel is None else panel
    inv_rows, acc_rows = [], []
    capacity = cfg.COLLECTOR_CALLS_PER_WEEK * 4          # one month of call slots
    for t in month_ends(cfg.REPLAY_START, cfg.REPLAY_END):
        model = train(panel, known_by=t)
        x = build_features(led, t)
        x["p_serious_delay"] = model.predict_proba(x[FEATURES])[:, 1]
        x["expected_at_risk"] = x.open_amount * x.p_serious_delay
        x["reasons"] = ""
        acc, _ = accounts_from_scored(x, led.customers)
        over = (acc.treatment == "3 Collector call") & (acc.call_week > 4)
        acc.loc[over, "treatment"] = "3 Collector call (over capacity)"
        acc["as_of"] = t
        acc_rows.append(acc[["as_of", "customer_id", "treatment", "open_ar", "overdue_usd", "oldest_dpd"]])
        inv_rows.append(x[["invoice_id", "customer_id", "dispute_open"]].assign(as_of=t).merge(
            acc[["customer_id", "treatment"]], on="customer_id"))
    return pd.concat(inv_rows, ignore_index=True), pd.concat(acc_rows, ignore_index=True)


# --------------------------------------------------------------------------
# 2. Apply the strategy to the ledger
# --------------------------------------------------------------------------
def apply_strategy(led: Ledger, inv_treat: pd.DataFrame, acc_treat: pd.DataFrame,
                   effects: dict, levers=LEVERS):
    inv, pay = led.invoices.copy(), led.payments.copy()
    stats = {"exposure_avoided": 0.0, "recovered_gross": 0.0, "good_revenue_held": 0.0, "accounts_held": 0}

    # ---- timing levers: earlier settle date for paid invoices ----
    r = inv_treat.merge(inv[["invoice_id", "invoice_date", "due_date", "settle_date"]], on="invoice_id")
    r = r[r.settle_date.notna()]
    r["lever"] = r.treatment.map(TREATMENT_LEVER)
    r = r[r.lever.isin(levers)].copy()
    if len(r):
        r["effect"] = r.lever.map(effects).fillna(0.0)
        floor = r.as_of + cfg.ACTION_LAG_DAYS * DAY
        late = (r.settle_date - r.due_date).dt.days.clip(lower=0)
        new = r.due_date + pd.to_timedelta(np.round(late * (1 - r.effect)).astype(float), unit="D")

        d = led.disputes.drop_duplicates("invoice_id").set_index("invoice_id")
        is_disp = (r.lever == "dispute_desk") & (r.dispute_open == 1) & r.invoice_id.isin(d.index)
        raised = r.invoice_id.map(d["raised_date"])
        resolved = r.invoice_id.map(d["resolved_date"])
        remaining = (resolved - np.maximum(raised, r.as_of)).dt.days.clip(lower=0).fillna(0)
        new_disp = r.settle_date - pd.to_timedelta(np.round(remaining * r.effect).astype(float), unit="D")
        new = new.where(~is_disp, new_disp)
        # the dispute desk only speeds up the disputed invoices; it does not chase the rest
        new = new.where(~((r.lever == "dispute_desk") & ~is_disp), r.settle_date)
        r["new_settle"] = np.maximum(new, floor).where(lambda s: s < r.settle_date, r.settle_date)
        new_settle = r.groupby("invoice_id")["new_settle"].min()
        moved = pd.to_datetime(pay.invoice_id.map(new_settle))
        pay["payment_date"] = pay.payment_date.where(~(moved < pay.payment_date), moved)

    # ---- billing fixed at source (Revenue Leakage Detector): billing-error disputes never happen.
    # The invoice then pays the dispute's duration earlier, but no earlier than the customer
    # would have paid an undisputed invoice (the dispute was raised before that point).
    if "billing_fix" in levers:
        bd = led.disputes[led.disputes.reason.isin(BILLING_ERROR_REASONS) & led.disputes.resolved_date.notna()]
        bd = bd.drop_duplicates("invoice_id").merge(inv[["invoice_id", "due_date", "settle_date"]], on="invoice_id")
        bd = bd[bd.settle_date.notna()]
        saved = pd.to_timedelta((bd.resolved_date - bd.raised_date).dt.days.astype(float), unit="D")
        fixed = np.maximum(bd.settle_date - saved, bd.raised_date)
        fixed = pd.Series(fixed.values, index=bd.invoice_id.values)
        moved = pd.to_datetime(pay.invoice_id.map(fixed))
        pay["payment_date"] = pay.payment_date.where(~(moved < pay.payment_date), moved)

    # ---- credit hold: stop invoicing a held account; the invoices it never paid are avoided ----
    holds = acc_treat[acc_treat.treatment.str.startswith("2 Escalate")].groupby("customer_id")["as_of"].min()
    keep = pd.Series(True, index=inv.index)
    if "credit_hold" in levers and len(holds):
        held_from = inv.customer_id.map(holds)
        stopped = (inv.invoice_date > held_from) & inv.settle_date.isna()
        stats["exposure_avoided"] = float(inv.loc[stopped, "amount"].sum())
        # the cost of a wrong hold: invoices the held account DID pay (assumed released, not lost)
        good = (inv.invoice_date > held_from) & inv.settle_date.notna()
        stats["good_revenue_held"] = float(inv.loc[good, "amount"].sum())
        stats["accounts_held"] = int(len(holds))
        keep = ~stopped

    # ---- escalation / agency recovery on the held account's unpaid overdue balance ----
    extra = []
    if "recovery" in levers:
        for cid, h in holds.items():
            when = h + cfg.RECOVERY_LAG_DAYS * DAY
            if when > cfg.SNAPSHOT:
                continue
            o = open_items(led, h)
            o = o[(o.customer_id == cid) & (o.days_past_due > 0) & o.settle_date.isna()]
            for _, it in o.iterrows():
                amt = round(it.open_amount * effects["recovery"], 2)
                extra.append({"payment_id": f"R-{it.invoice_id}", "customer_id": cid,
                              "invoice_id": it.invoice_id, "payment_date": when, "amount": amt})
                stats["recovered_gross"] += amt
    if extra:
        pay = pd.concat([pay, pd.DataFrame(extra)], ignore_index=True)

    inv_kept = inv[keep]
    pay = pay[pay.invoice_id.isin(inv_kept.invoice_id)]
    new_led = assemble(led.customers, inv_kept, pay, led.disputes, led.dunning)
    return new_led, stats


# --------------------------------------------------------------------------
# 3. Measure
# --------------------------------------------------------------------------
def measure(led: Ledger, stats=None) -> dict:
    k = kpis.monthly_kpis(led, start=pd.Timestamp("2025-12-31"))
    now = k.iloc[-1]
    o = open_items(led, cfg.SNAPSHOT)
    window = led.payments[(led.payments.payment_date > pd.Timestamp("2025-12-31")) &
                          (led.payments.payment_date <= cfg.SNAPSHOT)]
    m = {"dso_today": float(now.dso), "add_today": float(now["add"]), "cei_avg_2026": float(k.cei.iloc[1:].mean()),
         "dso_avg_2026": float(k.dso.iloc[1:].mean()), "open_ar_today": float(now.open_ar),
         "open_ar_avg_2026": float(k.open_ar.iloc[1:].mean()),
         "bad_debt_today": float(o.loc[o.days_past_due > cfg.BAD_DEBT_DPD, "open_amount"].sum()),
         "cash_collected_2026": float(window.amount.sum()), "kpis": k}
    m.update(stats or {"exposure_avoided": 0.0, "recovered_gross": 0.0, "good_revenue_held": 0.0,
                       "accounts_held": 0})
    return m


def compare(asis: dict, tobe: dict, months=10) -> dict:
    # Working capital = the AR the company has to fund, averaged over the 2026 month-ends.
    # (Paying in July instead of August does not change October's AR, but it does
    # lower the balance carried in between.)
    wc = asis["open_ar_avg_2026"] - tobe["open_ar_avg_2026"]
    fee = tobe["recovered_gross"] * cfg.AGENCY_FEE
    return {
        "dso_avg_reduction_days": asis["dso_avg_2026"] - tobe["dso_avg_2026"],
        "dso_today_reduction_days": asis["dso_today"] - tobe["dso_today"],
        "ar_today_reduction": asis["open_ar_today"] - tobe["open_ar_today"],
        "extra_cash_collected": tobe["cash_collected_2026"] - asis["cash_collected_2026"],
        "cei_avg_change_pts": tobe["cei_avg_2026"] - asis["cei_avg_2026"],
        "working_capital_released": wc,
        "financing_saving_per_year": wc * cfg.COST_OF_CAPITAL,
        "bad_debt_reduction": asis["bad_debt_today"] - tobe["bad_debt_today"],
        "exposure_avoided": tobe["exposure_avoided"],
        "good_revenue_held": tobe["good_revenue_held"],
        "accounts_held": tobe["accounts_held"],
        "recovered_net_of_fee": tobe["recovered_gross"] - fee,
        "agency_fees": fee,
        "dispute_desk_cost": cfg.DISPUTE_DESK_COST_PER_YEAR * months / 12,
    }


def run(led: Ledger, history=None):
    inv_treat, acc_treat = history or treatment_history(led)
    asis = measure(led)
    out = {"asis": asis, "scenarios": {}, "levers": {}, "tornado": {}}
    for name, eff in cfg.SCENARIOS.items():
        nl, st = apply_strategy(led, inv_treat, acc_treat, eff)
        tobe = measure(nl, st)
        out["scenarios"][name] = {"tobe": tobe, "delta": compare(asis, tobe)}
    base = cfg.SCENARIOS["base"]
    for lever in LEVERS:                                   # each lever on its own, base effects
        nl, st = apply_strategy(led, inv_treat, acc_treat, base, levers=[lever])
        out["levers"][lever] = compare(asis, measure(nl, st))
    for key in base:                                       # one assumption at a time to low / high
        row = {}
        for side in ("low", "high"):
            eff = dict(base, **{key: cfg.SCENARIOS[side][key]})
            nl, st = apply_strategy(led, inv_treat, acc_treat, eff)
            row[side] = compare(asis, measure(nl, st))
        out["tornado"][key] = row
    nl, st = apply_strategy(led, inv_treat, acc_treat, base, levers=["billing_fix"])
    out["billing_fix"] = compare(asis, measure(nl, st))
    nl, st = apply_strategy(led, inv_treat, acc_treat, base, levers=LEVERS + ["billing_fix"])
    out["all_plus_billing_fix"] = compare(asis, measure(nl, st))
    out["treatment_months"] = acc_treat.groupby("treatment").size()
    return out


LEVER_LABELS = {"call": "Collector calls (risk-ranked, capped at capacity)",
                "firm_reminder": "Firm automated reminders", "pre_due": "Pre-due checks on big invoices",
                "dispute_desk": "Dispute desk", "credit_hold": "Credit hold on very-high-risk accounts",
                "recovery": "Escalation / agency recovery"}
ASSUMPTION_LABELS = {"call": "Collector call cuts lateness by", "firm_reminder": "Firm reminder cuts lateness by",
                     "pre_due": "Pre-due check cuts lateness by",
                     "dispute_desk": "Dispute desk cuts remaining dispute time by",
                     "recovery": "Share of escalated unpaid balance recovered"}


def _k(x):
    return f"{x/1e3:,.0f}K" if abs(x) < 1e6 else f"{x/1e6:,.2f}M"


def monthly_paths(led, history):
    """DSO and AR by month: as-is vs to-be (base)."""
    inv_treat, acc_treat = history
    nl, _ = apply_strategy(led, inv_treat, acc_treat, cfg.SCENARIOS["base"])
    a = kpis.monthly_kpis(led, start=pd.Timestamp("2025-12-31"))
    b = kpis.monthly_kpis(nl, start=pd.Timestamp("2025-12-31"))
    return pd.DataFrame({"month_end": a.month_end, "open_ar_asis": a.open_ar, "open_ar_tobe": b.open_ar,
                         "dso_asis": a.dso, "dso_tobe": b.dso, "cei_asis": a.cei, "cei_tobe": b.cei,
                         "ar_90_plus_asis": a.ar_90_plus, "ar_90_plus_tobe": b.ar_90_plus})


def write_report(out: dict, paths: pd.DataFrame, path=None):
    path = path or cfg.OUTPUT_DIR / "cash_impact_report.md"
    s = {n: v["delta"] for n, v in out["scenarios"].items()}
    a = out["asis"]
    rows = [("Average DSO in 2026 (days lower)", "dso_avg_reduction_days", "{:.1f}"),
            ("DSO on 31 Oct 2026 (days lower)", "dso_today_reduction_days", "{:.1f}"),
            ("Average AR funded in 2026 (working capital released, USD)", "working_capital_released", "k"),
            (f"Financing saving per year at {cfg.COST_OF_CAPITAL:.0%} (USD)", "financing_saving_per_year", "k"),
            ("Invoices not issued to accounts that never paid (USD)", "exposure_avoided", "k"),
            (f"Cash recovered from escalated accounts, net of {cfg.AGENCY_FEE:.0%} fee (USD)", "recovered_net_of_fee", "k"),
            (f"AR more than {cfg.BAD_DEBT_DPD} days overdue on 31 Oct (USD lower)", "bad_debt_reduction", "k"),
            ("Collection effectiveness, 2026 average (points higher)", "cei_avg_change_pts", "{:.1f}"),
            ("Cost: dispute desk, 10 months (USD)", "dispute_desk_cost", "k")]

    def cell(v, f):
        return _k(v) if f == "k" else f.format(v)

    L = ["# Cash-flow impact: Jan-Oct 2026 replayed under the risk-based strategy", "",
         "Each month-end from Jan to Sep 2026 the worklist is rebuilt with only what was known that day, "
         "the to-be treatment is applied, and the ledger is recalculated. As-is = what actually happened "
         f"(average DSO {a['dso_avg_2026']:.1f} days, DSO {a['dso_today']:.1f} on 31 Oct, average AR "
         f"USD {_k(a['open_ar_avg_2026'])}).", "",
         "| Impact | Low | **Base** | High |", "| --- | ---: | ---: | ---: |"]
    for label, key, f in rows:
        L.append(f"| {label} | {cell(s['low'][key], f)} | **{cell(s['base'][key], f)}** | {cell(s['high'][key], f)} |")

    L += ["", "## Where the impact comes from (base assumptions, one lever at a time)", "",
          "| Lever | Avg DSO (days) | Working capital released | Invoices not issued | Recovered (net) |",
          "| --- | ---: | ---: | ---: | ---: |"]
    for lever, d in out["levers"].items():
        L.append(f"| {LEVER_LABELS[lever]} | {d['dso_avg_reduction_days']:.1f} | {_k(d['working_capital_released'])} | "
                 f"{_k(d['exposure_avoided'])} | {_k(d['recovered_net_of_fee'])} |")
    L += ["", "Levers overlap (an invoice can get a call and then a credit hold), so the rows do not add up exactly to the base column.", "",
          "## Fixing billing at source (link to the Revenue Leakage Detector)", "",
          "If the billing errors found in project 1 were fixed before invoicing, the disputes they cause "
          "would not happen. Replaying 2026 with those disputes removed:", "",
          "| | Billing fix alone | Collections strategy (base) | Both |", "| --- | ---: | ---: | ---: |"]
    bf, al = out["billing_fix"], out["all_plus_billing_fix"]
    for label, key, f in rows[:3]:
        L.append(f"| {label} | {cell(bf[key], f)} | {cell(s['base'][key], f)} | {cell(al[key], f)} |")

    L += ["", "## Sensitivity: working capital released when one assumption moves to low / high", "",
          "| Assumption | Low | Base value | High | WC released at low | at high |",
          "| --- | ---: | ---: | ---: | ---: | ---: |"]
    lo, ba, hi = cfg.SCENARIOS["low"], cfg.SCENARIOS["base"], cfg.SCENARIOS["high"]
    order = sorted(out["tornado"], key=lambda k: -(out["tornado"][k]["high"]["working_capital_released"]
                                                  - out["tornado"][k]["low"]["working_capital_released"]))
    for k in order:
        t = out["tornado"][k]
        L.append(f"| {ASSUMPTION_LABELS[k]} | {lo[k]:.0%} | {ba[k]:.0%} | {hi[k]:.0%} | "
                 f"{_k(t['low']['working_capital_released'])} | {_k(t['high']['working_capital_released'])} |")
    b = s["base"]
    hold_precision = b["exposure_avoided"] / max(b["exposure_avoided"] + b["good_revenue_held"], 1)
    L += ["", "The credit hold needs no effect assumption: it only stops invoices the account then never paid. "
          "It is the same in every scenario.", "",
          "## Credit hold: right and wrong calls", "",
          f"{b['accounts_held']} accounts were put on hold during the replay. After the hold they were sent "
          f"USD {_k(b['exposure_avoided'])} of invoices they never paid, and USD {_k(b['good_revenue_held'])} "
          f"they did pay, so **{hold_precision:.0%} of the held USD was money that would never have come in**. "
          "The paid invoices are good revenue a hold would have delayed until the account caught up. "
          "That is why the hold is a Finance Manager review, not an automatic switch.", "",
          "## Month by month (base)", "", paths.to_markdown(index=False, floatfmt=",.1f"), "",
          "## Treatment-months assigned during the replay", "",
          out["treatment_months"].rename("account-months").to_markdown(), "",
          "## What this replay does not capture", "",
          "* Effects are assumptions, incremental to the current process, until tested with a holdout group "
          "(for example, half the call list called, half not, for one quarter).",
          "* Invoices still open on 31 Oct have no actual pay date to improve on, so they get no timing benefit "
          "(conservative).",
          "* Treatments act at month-end; a weekly worklist would act sooner (conservative).",
          "* \"Invoices not issued\" is bad debt avoided, not new cash. The cash saving is the cost of serving "
          "those accounts, and a hold can delay good revenue if the customer was about to pay.", ""]
    path.write_text("\n".join(L), encoding="utf-8")
    return path
