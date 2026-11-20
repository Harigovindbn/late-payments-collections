# Collections summary as of 2026-10-31

## Where we are

| KPI | A year ago | Today |
| --- | ---: | ---: |
| Open AR | USD 5.72M | USD 6.93M |
| DSO (days) | 36.3 | **57.0** |
| Best possible DSO | 29.6 | 31.6 |
| Average days delinquent (DSO - BPDSO) | 6.7 | **25.4** |
| Collection effectiveness index | 82.5% | **50.4%** |
| AR over 90 days | 0.0% | **17.9%** |

## Ageing today

| ageing_bucket   |   invoices |   open_usd |   share |
|:----------------|-----------:|-----------:|--------:|
| Current         |        392 |  3,839,906 |    55.4 |
| 1-30            |        114 |  1,084,552 |    15.7 |
| 31-60           |         43 |    436,299 |     6.3 |
| 61-90           |         37 |    326,276 |     4.7 |
| 90+             |        131 |  1,238,723 |    17.9 |

## Disputes slow cash down

Undisputed invoices are paid 12 days late on average. Disputed ones:

| reason                   |   invoices |       usd |   avg_days_late |   median_days_late |
|:-------------------------|-----------:|----------:|----------------:|-------------------:|
| Amount does not match PO |        512 | 5,204,306 |            34.6 |               35   |
| Over-charged (tax rate)  |         52 |   673,991 |            32.5 |               35.5 |
| PO number missing        |         62 |   650,503 |            36.1 |               37   |
| Wrong billing contact    |         59 |   519,024 |            18.2 |               16   |
| Service issue            |         56 |   416,270 |            33.9 |               29   |

## Risk-based prioritisation (walk-forward backtest, Jan-Sep 2026)

* AUC **0.876** for the risk score vs 0.638 for days past due alone.
* With capacity for 40 accounts a week, the list reaches as-is: oldest first **62%**; biggest overdue first **66%**; risk-based: expected USD at risk **71%** of the USD that really went seriously late.

## Today's treatment plan

| treatment                               |   accounts |   open_ar |   overdue_usd |   expected_at_risk |   share_of_risk |
|:----------------------------------------|-----------:|----------:|--------------:|-------------------:|----------------:|
| 1 Dispute desk                          |         28 |   607,855 |       174,521 |            166,691 |            0.05 |
| 2 Escalate: credit hold                 |          7 |   169,650 |       117,270 |            144,281 |            0.05 |
| 2 Escalate: credit hold + agency review |         19 | 1,821,462 |     1,627,925 |          1,797,068 |            0.57 |
| 3 Collector call                        |         17 |   880,509 |       436,219 |            471,689 |            0.15 |
| 4 Pre-due check                         |         12 |   578,980 |       189,468 |            166,955 |            0.05 |
| 5 Firm automated reminder               |         13 |   325,121 |       200,030 |            103,716 |            0.03 |
| 6 Standard reminder                     |        158 | 2,542,178 |       340,416 |            289,617 |            0.09 |

## Top 15 accounts

|   priority_rank | name                       | treatment                               |   open_ar |   overdue_usd |   oldest_dpd |   risk | why                                                                                                  |
|----------------:|:---------------------------|:----------------------------------------|----------:|--------------:|-------------:|-------:|:-----------------------------------------------------------------------------------------------------|
|               1 | Crescent Analytics Limited | 2 Escalate: credit hold + agency review |   407,488 |       369,105 |          242 |  0.999 | paying 120 days later than a year ago; 242 days past due; at 326% of credit limit                    |
|               2 | Pacific Retail DAC         | 2 Escalate: credit hold + agency review |   260,554 |       241,009 |          380 |  0.936 | 168 days past due; at 465% of credit limit; 9 broken promise(s) to pay                               |
|               3 | Nova Construction LLC      | 2 Escalate: credit hold + agency review |   183,932 |       162,527 |          153 |  0.997 | paying 120 days later than a year ago; 153 days past due; at 230% of credit limit                    |
|               4 | Red Hospitality Pty Ltd    | 2 Escalate: credit hold + agency review |   182,196 |       144,413 |          243 |  0.999 | paying 120 days later than a year ago; at 289% of credit limit; 8 broken promise(s) to pay           |
|               5 | Willow Media Pty Ltd       | 2 Escalate: credit hold + agency review |   160,676 |       159,240 |          334 |  1     | paying 120 days later than a year ago; 304 days past due; at 342% of credit limit                    |
|               6 | Nova Motors B.V.           | 2 Escalate: credit hold + agency review |   146,126 |       121,762 |          153 |  0.996 | paying 120 days later than a year ago; at 298% of credit limit; 83% of balance overdue               |
|               7 | Titan Logistics B.V.       | 2 Escalate: credit hold + agency review |   127,596 |       127,596 |          198 |  0.999 | paying 120 days later than a year ago; 107 days past due; at 440% of credit limit                    |
|               8 | Quantum Energy Pty Ltd     | 2 Escalate: credit hold + agency review |    89,335 |        71,597 |          122 |  0.995 | paying 114 days later than a year ago; at 308% of credit limit; 80% of balance overdue               |
|               9 | North Labs FZ-LLC          | 3 Collector call                        |   124,810 |        72,929 |           62 |  0.644 | paying 31 days later than a year ago; 48% of invoices paid 30+ days late; 5 broken promise(s) to pay |
|              10 | Willow Telecom DAC         | 3 Collector call                        |   134,792 |        67,396 |           30 |  0.518 | 69% of invoices paid 30+ days late; at 127% of credit limit; 50% of balance overdue                  |
|              11 | Zenith Pharma DAC          | 2 Escalate: credit hold + agency review |    56,283 |        50,100 |          242 |  0.999 | paying 120 days later than a year ago; 153 days past due; at 375% of credit limit                    |
|              12 | Granite Education Pty Ltd  | 2 Escalate: credit hold + agency review |    50,189 |        50,189 |          122 |  0.999 | 122 days past due; paying 109 days later than a year ago; 100% of balance overdue                    |
|              13 | Cedar Pharma Pty Ltd       | 2 Escalate: credit hold                 |    54,093 |        32,449 |           92 |  0.88  | 92 days past due; paying 51 days later than a year ago; 56% of invoices paid 30+ days late           |
|              14 | Summit Foods Pty Ltd       | 3 Collector call                        |    85,965 |        27,730 |           31 |  0.488 | 82% of invoices paid 30+ days late; at 88% of credit limit                                           |
|              15 | River Foods AG             | 2 Escalate: credit hold + agency review |    43,361 |        28,783 |          123 |  0.962 | paying 118 days later than a year ago; at 167% of credit limit; 66% of balance overdue               |
