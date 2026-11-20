"""
Entry point:  python -m src.run_pipeline

  1. KPIs month by month (DSO, best-possible DSO, ADD, CEI, % 90+)
  2. Dispute impact on days-to-pay (the link to the Revenue Leakage Detector)
  3. Risk score: walk-forward backtest vs today's oldest-first rule, then the production fit
  4. Today's worklist: account priority, treatment, collector call weeks
  5. Cash-flow impact: Jan-Oct 2026 replayed under the to-be strategy, low/base/high

Outputs in output/: kpis_monthly.csv, ageing_today.csv, dispute_impact.csv,
risk_model_report.md, worklist_accounts.csv, worklist_invoices.csv, collections_summary.md,
cash_impact_report.md, cash_impact_monthly.csv
"""

import time

import pandas as pd

from . import config as cfg
from . import cash_impact, kpis, ledger, risk_model, worklist


def main():
    t0 = time.time()
    cfg.OUTPUT_DIR.mkdir(exist_ok=True)
    led = ledger.load()

    k = kpis.monthly_kpis(led)
    k.to_csv(cfg.OUTPUT_DIR / "kpis_monthly.csv", index=False)
    ageing = ledger.ageing_summary(ledger.open_items(led, cfg.SNAPSHOT))
    ageing.to_csv(cfg.OUTPUT_DIR / "ageing_today.csv")
    disp = kpis.dispute_impact(led)
    disp.to_csv(cfg.OUTPUT_DIR / "dispute_impact.csv")
    print(f"[1-2] KPIs and dispute impact ({time.time() - t0:.0f}s)")

    model, panel, res = risk_model.fit_and_save(led)
    coefs = risk_model.coefficients(model)
    risk_model.write_report(res, coefs)
    print(f"[3] risk model: walk-forward AUC {res['auc']:.3f} vs {res['auc_days_past_due_only']:.3f} "
          f"for days-past-due alone ({time.time() - t0:.0f}s)")

    acc, items = worklist.build_worklist(led, model)
    acc.to_csv(cfg.OUTPUT_DIR / "worklist_accounts.csv", index=False)
    items.to_csv(cfg.OUTPUT_DIR / "worklist_invoices.csv", index=False)
    summary = worklist.treatment_summary(acc)
    write_summary(k, ageing, disp, res, summary, acc)
    print(f"[4] worklist: {len(acc)} accounts, {int((acc.call_week == 1).sum())} on this week's call list "
          f"({time.time() - t0:.0f}s)")

    history = cash_impact.treatment_history(led, panel)
    out = cash_impact.run(led, history)
    paths = cash_impact.monthly_paths(led, history)
    paths.to_csv(cfg.OUTPUT_DIR / "cash_impact_monthly.csv", index=False)
    cash_impact.write_report(out, paths)
    b = out["scenarios"]["base"]["delta"]
    print(f"[5] cash impact (base): average DSO -{b['dso_avg_reduction_days']:.1f} days, "
          f"working capital released USD {b['working_capital_released']/1e3:,.0f}K, "
          f"invoices not issued to non-payers USD {b['exposure_avoided']/1e3:,.0f}K ({time.time() - t0:.0f}s)")


def md(df, index=True):
    """Markdown table with thousands separators on money-sized numbers."""
    d = df.copy()
    for c in d.columns:
        if pd.api.types.is_numeric_dtype(d[c]) and d[c].abs().max() >= 1000:
            d[c] = d[c].map(lambda v: f"{v:,.0f}")
    return d.to_markdown(index=index)


def usd(x):
    return f"USD {x/1e6:.2f}M" if abs(x) >= 1e6 else f"USD {x/1e3:,.0f}K"


def write_summary(k, ageing, disp, res, summary, acc):
    now, yr = k.iloc[-1], k[k.month_end == (cfg.SNAPSHOT - pd.DateOffset(years=1)).date()].iloc[0]
    cap = res["capacity"][cfg.COLLECTOR_CALLS_PER_WEEK]
    nod = disp.loc["No dispute", "avg_days_late"]
    lines = [
        f"# Collections summary as of {cfg.SNAPSHOT.date()}", "",
        "## Where we are", "",
        "| KPI | A year ago | Today |", "| --- | ---: | ---: |",
        f"| Open AR | {usd(yr.open_ar)} | {usd(now.open_ar)} |",
        f"| DSO (days) | {yr.dso} | **{now.dso}** |",
        f"| Best possible DSO | {yr.bpdso} | {now.bpdso} |",
        f"| Average days delinquent (DSO - BPDSO) | {yr['add']} | **{now['add']}** |",
        f"| Collection effectiveness index | {yr.cei}% | **{now.cei}%** |",
        f"| AR over 90 days | {yr.pct_90_plus}% | **{now.pct_90_plus}%** |", "",
        "## Ageing today", "", md(ageing.assign(share=(ageing.share * 100).round(1))), "",
        "## Disputes slow cash down", "",
        f"Undisputed invoices are paid {nod:.0f} days late on average. Disputed ones:", "",
        md(disp.drop(index="No dispute")), "",
        "## Risk-based prioritisation (walk-forward backtest, Jan-Sep 2026)", "",
        f"* AUC **{res['auc']:.3f}** for the risk score vs {res['auc_days_past_due_only']:.3f} for days past due alone.",
        f"* With capacity for {cfg.COLLECTOR_CALLS_PER_WEEK} accounts a week, the list reaches "
        + "; ".join(f"{name} **{v:.0%}**" for name, v in cap.items())
        + " of the USD that really went seriously late.", "",
        "## Today's treatment plan", "", md(summary), "",
        "## Top 15 accounts", "",
        acc.head(15)[["priority_rank", "name", "treatment", "open_ar", "overdue_usd", "oldest_dpd",
                      "risk", "why"]].pipe(md, index=False), ""]
    (cfg.OUTPUT_DIR / "collections_summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
