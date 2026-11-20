"""Tests for the ledger, the no-look-ahead rule, the target definition and the treatment rules."""

import pandas as pd
import pytest

from src import config as cfg
from src.features import add_target, build_features
from src.ledger import Ledger, open_items
from src.worklist import assign_treatment

T = pd.Timestamp


def tiny_ledger():
    cust = pd.DataFrame({"customer_id": ["A", "B"], "name": ["Alpha", "Beta"],
                         "billing_country": ["AU", "DE"], "segment": ["SMB", "Enterprise"],
                         "payment_terms_days": [30, 60], "credit_limit": [10_000, 50_000]})
    inv = pd.DataFrame({
        "invoice_id": ["I1", "I2", "I3"], "customer_id": ["A", "A", "B"],
        "invoice_date": [T("2026-01-01"), T("2026-02-01"), T("2026-01-01")],
        "due_date": [T("2026-01-31"), T("2026-03-03"), T("2026-03-02")],
        "payment_terms_days": [30, 30, 60], "amount": [1000.0, 2000.0, 5000.0]})
    pay = pd.DataFrame({"payment_id": ["P1", "P2", "P3"], "customer_id": ["A", "A", "B"],
                        "invoice_id": ["I1", "I2", "I3"],
                        "payment_date": [T("2026-02-10"), T("2026-03-20"), T("2026-04-30")],
                        "amount": [1000.0, 500.0, 5000.0]})
    disp = pd.DataFrame({"dispute_id": ["D1"], "invoice_id": ["I3"], "customer_id": ["B"],
                         "raised_date": [T("2026-03-05")], "reason": ["Amount does not match PO"],
                         "resolved_date": [T("2026-04-20")], "status": ["Resolved"]})
    dun = pd.DataFrame(columns=["activity_id", "invoice_id", "customer_id", "activity_date",
                                "channel", "step", "outcome", "promised_date", "promise_kept"])
    dun["promised_date"] = pd.to_datetime(dun["promised_date"])
    # settle dates as ledger.load() would derive them
    inv["settle_date"] = [T("2026-02-10"), pd.NaT, T("2026-04-30")]
    inv["days_late"] = (inv.settle_date - inv.due_date).dt.days
    inv = inv.merge(cust[["customer_id", "segment", "billing_country"]], on="customer_id")
    return Ledger(cust, inv, pay, disp, dun)


def test_open_items_balance_and_age():
    o = open_items(tiny_ledger(), T("2026-03-31")).set_index("invoice_id")
    assert set(o.index) == {"I2", "I3"}                  # I1 was paid in February
    assert o.loc["I2", "open_amount"] == pytest.approx(1500.0)   # part-paid
    assert o.loc["I2", "partially_paid"] == 1
    assert o.loc["I2", "days_past_due"] == 28
    assert o.loc["I3", "dispute_open"] == 1
    assert o.loc["I3", "ageing_bucket"] == "1-30"


def test_dispute_closed_after_resolution():
    o = open_items(tiny_ledger(), T("2026-04-25")).set_index("invoice_id")
    assert o.loc["I3", "dispute_open"] == 0


def test_features_ignore_the_future():
    """Features as of March must not change when later payments exist or not."""
    led = tiny_ledger()
    before = build_features(led, T("2026-03-31"))
    led.payments = led.payments[led.payments.payment_date <= T("2026-03-31")]
    led.invoices.loc[led.invoices.settle_date > T("2026-03-31"), "settle_date"] = pd.NaT
    after = build_features(led, T("2026-03-31"))
    cols = ["open_amount", "cust_avg_days_late", "cust_overdue_share", "cust_trend", "dispute_open"]
    pd.testing.assert_frame_equal(before[cols].reset_index(drop=True), after[cols].reset_index(drop=True))


def test_target_horizon():
    led = tiny_ledger()
    x = build_features(led, T("2026-01-31"))
    old = cfg.SNAPSHOT
    cfg.SNAPSHOT = T("2026-10-31")
    try:
        y = add_target(x).set_index("invoice_id")
    finally:
        cfg.SNAPSHOT = old
    # I1 due 31 Jan, paid 10 Feb: within 30 days -> 0
    assert y.loc["I1", "y"] == 0
    # I3 due 2 Mar, paid 30 Apr (dispute): more than 30 days late -> 1
    assert y.loc["I3", "y"] == 1


def account(**kw):
    base = dict(open_disputes=0, disputed_usd=0.0, overdue_usd=10_000.0, risk=0.1, oldest_dpd=10,
                expected_at_risk=1_000.0, due_soon_usd=0.0)
    return pd.Series(base | kw)


@pytest.mark.parametrize("kw, expected", [
    (dict(open_disputes=1, disputed_usd=8_000.0), "1 Dispute desk"),
    (dict(risk=0.9, oldest_dpd=75), "2 Escalate: credit hold"),
    (dict(risk=0.9, oldest_dpd=130), "2 Escalate: credit hold + agency review"),
    (dict(risk=0.5, expected_at_risk=20_000.0), "3 Collector call"),
    (dict(risk=0.25, due_soon_usd=30_000.0), "4 Pre-due check"),
    (dict(risk=0.5, expected_at_risk=500.0), "5 Firm automated reminder"),
    (dict(), "6 Standard reminder"),
])
def test_treatment_rules(kw, expected):
    assert assign_treatment(account(**kw)) == expected


def test_small_dispute_does_not_block_collection():
    # a USD 500 dispute on a USD 50K overdue balance should not park the whole account
    a = account(open_disputes=1, disputed_usd=500.0, overdue_usd=50_000.0, risk=0.6,
                expected_at_risk=30_000.0)
    assert assign_treatment(a) == "3 Collector call"


# --------------------------------------------------------------------------
# Cash-flow replay
# --------------------------------------------------------------------------
from src.cash_impact import apply_strategy  # noqa: E402

EFFECTS = dict(call=0.5, firm_reminder=0.1, pre_due=0.3, dispute_desk=0.5, recovery=0.25)


def settle(led, invoice_id):
    return led.invoices.set_index("invoice_id").loc[invoice_id, "settle_date"]


def test_call_cuts_lateness_but_not_before_the_call():
    led = tiny_ledger()
    # I3 due 2 Mar, paid 30 Apr (59 days late). A call on 31 Mar halves lateness -> 31 Mar,
    # but nothing can pay before the call + 3 days.
    inv_treat = pd.DataFrame({"invoice_id": ["I3"], "customer_id": ["B"], "dispute_open": [0],
                              "as_of": [T("2026-03-31")], "treatment": ["3 Collector call"]})
    acc_treat = pd.DataFrame({"as_of": [T("2026-03-31")], "customer_id": ["B"], "treatment": ["3 Collector call"]})
    new, _ = apply_strategy(led, inv_treat, acc_treat, EFFECTS, levers=["call"])
    assert settle(new, "I3") == T("2026-04-03")
    assert settle(new, "I1") == settle(led, "I1")          # untouched


def test_treatment_never_makes_payment_later():
    led = tiny_ledger()
    inv_treat = pd.DataFrame({"invoice_id": ["I1"], "customer_id": ["A"], "dispute_open": [0],
                              "as_of": [T("2026-02-28")], "treatment": ["3 Collector call"]})
    acc_treat = pd.DataFrame({"as_of": [T("2026-02-28")], "customer_id": ["A"], "treatment": ["3 Collector call"]})
    new, _ = apply_strategy(led, inv_treat, acc_treat, EFFECTS, levers=["call"])
    assert settle(new, "I1") == settle(led, "I1")          # already paid 10 Feb


def test_credit_hold_stops_only_unpaid_later_invoices():
    led = tiny_ledger()
    # hold customer A on 15 Jan: I2 (issued 1 Feb, never fully paid) is not issued; I1 stays
    acc_treat = pd.DataFrame({"as_of": [T("2026-01-15")], "customer_id": ["A"],
                              "treatment": ["2 Escalate: credit hold"]})
    inv_treat = pd.DataFrame(columns=["invoice_id", "customer_id", "dispute_open", "as_of", "treatment"])
    new, st = apply_strategy(led, inv_treat, acc_treat, EFFECTS, levers=["credit_hold"])
    assert set(new.invoices.invoice_id) == {"I1", "I3"}
    assert st["exposure_avoided"] == pytest.approx(2000.0)
    assert st["good_revenue_held"] == 0.0
