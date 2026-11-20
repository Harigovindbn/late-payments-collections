"""
Central configuration: every collections-policy threshold lives here, so the
Credit Controller can change a rule without touching the analysis code.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

CUSTOMERS_CSV = DATA_DIR / "customers.csv"
INVOICES_CSV = DATA_DIR / "invoices.csv"
PAYMENTS_CSV = DATA_DIR / "payments.csv"
DISPUTES_CSV = DATA_DIR / "disputes.csv"
DUNNING_CSV = DATA_DIR / "dunning_log.csv"
TRUTH_CSV = DATA_DIR / "truth_customer_behaviour.csv"   # sanity checks only

SNAPSHOT = pd.Timestamp("2026-10-31")    # "today"

# Ageing buckets on days past due (standard AR ageing report)
AGEING_BINS = [-10_000, 0, 30, 60, 90, 10_000]
AGEING_LABELS = ["Current", "1-30", "31-60", "61-90", "90+"]

# --------------------------------------------------------------------------
# Risk model
# --------------------------------------------------------------------------
# Target: the invoice is still unpaid 30 days after max(today, due date), i.e. it
# will be more than 30 days late, or, if already overdue, still unpaid a month from now.
HORIZON_DAYS = 30
TRAIN_END = pd.Timestamp("2025-12-31")   # month-ends up to here train the model
PANEL_START = pd.Timestamp("2024-06-30") # first month-end with 6 months of history
LOOKBACK_DAYS = 365                      # customer payment history window
RECENT_DAYS = 90                         # "recent behaviour" window for the trend feature

# --------------------------------------------------------------------------
# Collections strategy (to-be policy)
# --------------------------------------------------------------------------
COLLECTOR_CALLS_PER_WEEK = 40    # 1 collector x 5 days x 8 accounts properly worked a day
HIGH_RISK = 0.40                 # account-weighted probability of serious delay
VERY_HIGH_RISK = 0.65
HIGH_VALUE_USD = 10_000          # expected USD at risk that justifies a human call
CREDIT_HOLD_DPD = 60             # oldest item this overdue + very high risk -> credit hold review
AGENCY_DPD = 120                 # oldest item this overdue -> legal / agency review
FIRM_REMINDER_DPD = 45           # age floor: nobody this overdue stays on the standard ladder
PRE_DUE_WINDOW_DAYS = 14        # large invoices due within this window get a courtesy check
PRE_DUE_MIN_USD = 15_000

# --------------------------------------------------------------------------
# Cash-flow impact (replay of Jan-Sep 2026 under the to-be strategy)
# --------------------------------------------------------------------------
REPLAY_START = pd.Timestamp("2026-01-31")
REPLAY_END = pd.Timestamp("2026-09-30")   # last month-end a treatment can still act before "today"
ACTION_LAG_DAYS = 3                       # earliest a treated invoice can pay after the action
BAD_DEBT_DPD = 120                        # AR this overdue at the snapshot is treated as bad debt
RECOVERY_LAG_DAYS = 60                    # escalation/agency cash arrives this long after the hold
COST_OF_CAPITAL = 0.08                    # annual rate used to value working capital released
AGENCY_FEE = 0.20                         # agency commission on recovered cash
DISPUTE_DESK_COST_PER_YEAR = 40_000       # 0.5 FTE billing analyst working disputes

# Treatment effects are ASSUMPTIONS, not measurements (see README): the share by which each
# to-be treatment cuts an invoice's remaining lateness, incremental to today's process.
SCENARIOS = {
    #               collector call, firm reminder, pre-due check, dispute desk*, recovery**
    "low":  dict(call=0.15, firm_reminder=0.05, pre_due=0.20, dispute_desk=0.30, recovery=0.10),
    "base": dict(call=0.25, firm_reminder=0.10, pre_due=0.35, dispute_desk=0.50, recovery=0.25),
    "high": dict(call=0.40, firm_reminder=0.15, pre_due=0.50, dispute_desk=0.70, recovery=0.40),
}
# * share of the remaining dispute-resolution time saved by a dedicated dispute desk
# ** share of an escalated account's unpaid overdue balance recovered (before agency fee)
