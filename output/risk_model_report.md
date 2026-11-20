# Late-payment risk score: backtest

Target: invoice still unpaid 30 days after max(month-end, due date).
Trained on month-ends up to 2025-12-31 (7,221 invoice-months); tested on Jan-Sep 2026 (5,622 invoice-months).

| Metric | Value |
| --- | ---: |
| Test base rate (invoices) | 33.2% |
| Test base rate (USD) | 32.6% |
| AUC, risk score | **0.876** |
| AUC, USD-weighted | 0.873 |
| AUC, days past due alone (as-is view) | 0.638 |
| Brier score | 0.127 |

## Which accounts reach a collector (avg 111 accounts with overdue AR per month)

Share of the USD that really went seriously late, sitting in the accounts each rule puts at the top of the list:

| Rule | Top 20 | Top 40 | Top 60 |
| --- | ---: | ---: | ---: |
| as-is: oldest first | 42.8% | 62.2% | 71.3% |
| biggest overdue first | 51.3% | 66.0% | 76.1% |
| risk-based: expected USD at risk | 57.3% | 70.8% | 81.5% |

## Calibration (test set, by risk decile)

|   decile |   rows |   predicted |   actual |
|---------:|-------:|------------:|---------:|
|        1 |    563 |       0.031 |    0.064 |
|        2 |    562 |       0.05  |    0.039 |
|        3 |    562 |       0.059 |    0.073 |
|        4 |    562 |       0.071 |    0.101 |
|        5 |    562 |       0.1   |    0.137 |
|        6 |    562 |       0.162 |    0.26  |
|        7 |    562 |       0.276 |    0.375 |
|        8 |    562 |       0.447 |    0.552 |
|        9 |    562 |       0.706 |    0.73  |
|       10 |    563 |       0.989 |    0.993 |

## Drivers (standardised coefficients; odds ratio per +1 standard deviation)

| feature              |   coef_per_sd |   odds_ratio_per_sd |
|:---------------------|--------------:|--------------------:|
| cust_trend           |         1.263 |               3.536 |
| cust_late30_share    |         0.839 |               2.315 |
| dpd_90_plus          |         0.833 |               2.3   |
| dpd_1_30             |        -0.731 |               0.481 |
| dpd_31_60            |        -0.638 |               0.528 |
| cust_credit_usage    |         0.484 |               1.622 |
| cust_overdue_share   |         0.479 |               1.615 |
| dispute_open         |         0.397 |               1.488 |
| cust_max_dpd         |        -0.286 |               0.751 |
| cust_no_history      |         0.258 |               1.294 |
| cust_broken_promises |         0.244 |               1.276 |
| dpd_61_90            |        -0.236 |               0.79  |
| terms_days           |         0.168 |               1.183 |
| days_to_due          |        -0.155 |               0.857 |
| partially_paid       |        -0.132 |               0.876 |
| cust_disputes_12m    |        -0.115 |               0.891 |
| log_amount           |        -0.066 |               0.937 |
| seg_enterprise       |        -0.062 |               0.94  |
| seg_smb              |         0.043 |               1.044 |
| cust_avg_days_late   |         0.032 |               1.033 |
