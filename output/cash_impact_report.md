# Cash-flow impact: Jan-Oct 2026 replayed under the risk-based strategy

Each month-end from Jan to Sep 2026 the worklist is rebuilt with only what was known that day, the to-be treatment is applied, and the ledger is recalculated. As-is = what actually happened (average DSO 44.5 days, DSO 57.0 on 31 Oct, average AR USD 6.24M).

| Impact | Low | **Base** | High |
| --- | ---: | ---: | ---: |
| Average DSO in 2026 (days lower) | 2.2 | **3.2** | 4.2 |
| DSO on 31 Oct 2026 (days lower) | 4.5 | **5.5** | 6.5 |
| Average AR funded in 2026 (working capital released, USD) | 383K | **514K** | 639K |
| Financing saving per year at 8% (USD) | 31K | **41K** | 51K |
| Invoices not issued to accounts that never paid (USD) | 763K | **763K** | 763K |
| Cash recovered from escalated accounts, net of 20% fee (USD) | 60K | **150K** | 239K |
| AR more than 120 days overdue on 31 Oct (USD lower) | 185K | **284K** | 384K |
| Collection effectiveness, 2026 average (points higher) | 3.2 | **4.7** | 6.3 |
| Cost: dispute desk, 10 months (USD) | 33K | **33K** | 33K |

## Where the impact comes from (base assumptions, one lever at a time)

| Lever | Avg DSO (days) | Working capital released | Invoices not issued | Recovered (net) |
| --- | ---: | ---: | ---: | ---: |
| Collector calls (risk-ranked, capped at capacity) | 0.6 | 85K | 0K | 0K |
| Firm automated reminders | 0.1 | 8K | 0K | 0K |
| Pre-due checks on big invoices | 0.5 | 71K | 0K | 0K |
| Dispute desk | 0.5 | 76K | 0K | 0K |
| Credit hold on very-high-risk accounts | 1.0 | 217K | 763K | 0K |
| Escalation / agency recovery | 0.5 | 67K | 0K | 150K |

Levers overlap (an invoice can get a call and then a credit hold), so the rows do not add up exactly to the base column.

## Fixing billing at source (link to the Revenue Leakage Detector)

If the billing errors found in project 1 were fixed before invoicing, the disputes they cause would not happen. Replaying 2026 with those disputes removed:

| | Billing fix alone | Collections strategy (base) | Both |
| --- | ---: | ---: | ---: |
| Average DSO in 2026 (days lower) | 2.0 | 3.2 | 4.7 |
| DSO on 31 Oct 2026 (days lower) | 0.0 | 5.5 | 5.5 |
| Average AR funded in 2026 (working capital released, USD) | 291K | 514K | 731K |

## Sensitivity: working capital released when one assumption moves to low / high

| Assumption | Low | Base value | High | WC released at low | at high |
| --- | ---: | ---: | ---: | ---: | ---: |
| Share of escalated unpaid balance recovered | 10% | 25% | 40% | 473K | 554K |
| Collector call cuts lateness by | 15% | 25% | 40% | 479K | 552K |
| Pre-due check cuts lateness by | 20% | 35% | 50% | 483K | 542K |
| Dispute desk cuts remaining dispute time by | 30% | 50% | 70% | 491K | 527K |
| Firm reminder cuts lateness by | 5% | 10% | 15% | 511K | 519K |

The credit hold needs no effect assumption: it only stops invoices the account then never paid. It is the same in every scenario.

## Credit hold: right and wrong calls

22 accounts were put on hold during the replay. After the hold they were sent USD 763K of invoices they never paid, and USD 35K they did pay, so **96% of the held USD was money that would never have come in**. The paid invoices are good revenue a hold would have delayed until the account caught up. That is why the hold is a Finance Manager review, not an automatic switch.

## Month by month (base)

| month_end   |   open_ar_asis |   open_ar_tobe |   dso_asis |   dso_tobe |   cei_asis |   cei_tobe |   ar_90_plus_asis |   ar_90_plus_tobe |
|:------------|---------------:|---------------:|-----------:|-----------:|-----------:|-----------:|------------------:|------------------:|
| 2025-12-31  |    5,929,282.1 |    5,929,282.1 |       36.9 |       36.9 |      nan   |      nan   |               0.0 |               0.0 |
| 2026-01-31  |    5,954,887.9 |    5,954,887.9 |       37.3 |       37.3 |       71.2 |       71.2 |          23,176.2 |          23,176.2 |
| 2026-02-28  |    6,564,022.6 |    6,317,506.9 |       41.0 |       39.4 |       72.2 |       76.4 |          40,193.2 |          40,193.2 |
| 2026-03-31  |    5,824,333.8 |    5,522,390.5 |       37.4 |       35.5 |       77.1 |       80.6 |          86,755.7 |          86,755.7 |
| 2026-04-30  |    5,879,749.9 |    5,560,427.1 |       38.5 |       36.5 |       72.6 |       76.2 |         137,324.6 |         136,673.6 |
| 2026-05-31  |    6,307,105.6 |    5,857,900.6 |       44.2 |       41.2 |       66.0 |       71.7 |         187,655.8 |         141,832.0 |
| 2026-06-30  |    6,141,735.1 |    5,588,401.2 |       44.0 |       40.6 |       68.7 |       74.3 |         405,790.0 |         350,754.4 |
| 2026-07-31  |    6,210,499.3 |    5,437,605.5 |       46.6 |       41.6 |       63.2 |       71.3 |         538,034.5 |         412,180.6 |
| 2026-08-31  |    6,134,541.8 |    5,416,466.6 |       47.6 |       43.1 |       55.9 |       60.4 |         716,265.6 |         549,140.4 |
| 2026-09-30  |    6,428,153.0 |    5,602,725.7 |       51.5 |       46.4 |       56.4 |       63.0 |         953,677.6 |         700,968.7 |
| 2026-10-31  |    6,925,754.8 |    5,976,209.0 |       57.0 |       51.5 |       50.4 |       56.0 |       1,238,723.2 |         837,695.2 |

## Treatment-months assigned during the replay

| treatment                               |   account-months |
|:----------------------------------------|-----------------:|
| 1 Dispute desk                          |              265 |
| 2 Escalate: credit hold                 |               20 |
| 2 Escalate: credit hold + agency review |               61 |
| 3 Collector call                        |              121 |
| 4 Pre-due check                         |               89 |
| 5 Firm automated reminder               |              106 |
| 6 Standard reminder                     |             1726 |

## What this replay does not capture

* Effects are assumptions, incremental to the current process, until tested with a holdout group (for example, half the call list called, half not, for one quarter).
* Invoices still open on 31 Oct have no actual pay date to improve on, so they get no timing benefit (conservative).
* Treatments act at month-end; a weekly worklist would act sooner (conservative).
* "Invoices not issued" is bad debt avoided, not new cash. The cash saving is the cost of serving those accounts, and a hold can delay good revenue if the customer was about to pay.
