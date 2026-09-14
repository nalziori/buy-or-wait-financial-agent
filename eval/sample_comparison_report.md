# Sample Comparison Report (25 sample_requests.csv)

Run: `gemini-3.5-flash`, 11 batched calls (9 message batches of ≤25, 2 image batches of ≤8), all 215 messages
and 16 images processed once, cached in `code/cache/llm_cache.json`. A second run of the same command made
**zero** new API calls (cache count stayed at 11 valid entries) — confirmed before writing this report.

Baseline for comparison: `--no-llm` (deterministic forecasting only, no image/message evidence at all).

## Requested metrics (with evidence extraction applied)

| Metric | Value |
|---|---|
| amount_safe_to_pay exact match (±0.01) | 3/25 (12%) |
| amount_safe_to_pay MAE | 187,280.76 |
| amount_safe_to_pay median absolute error | 737.00 |
| amount_safe_to_pay max error | 2,207,486.07 (request_04) |
| Overestimation count (pred > gold) | 10/25 |
| Underestimation count (pred < gold) | 12/25 |
| **Safety-critical overestimation rate** (pred > gold) | **10/25 (40%)** |
| affordability_status accuracy | 20/25 (80%) |
| recommended_payment_method accuracy | 21/25 (84%) |
| payment_plan accuracy | 20/25 (80%) |
| earliest_date_for_full_payment accuracy | 17/25 (68%) |
| spending_changes_needed accuracy | 21/25 (84%) |
| Overall exact match (all 6 axes incl. amount ±0.01) | 3/25 (12%) |

## Evidence extraction vs. deterministic forecasting — isolated

Same run, `--no-llm` baseline, identical metric set:

| Metric | No LLM | With LLM | Delta |
|---|---:|---:|---:|
| amount_safe_to_pay exact match | 3/25 | 3/25 | 0 |
| amount_safe_to_pay MAE | 187,623.32 | 187,280.76 | −342.56 (noise) |
| amount_safe_to_pay over/under | 10 / 12 | 10 / 12 | 0 |
| affordability_status | 20/25 | 20/25 | 0 |
| recommended_payment_method | 21/25 | 21/25 | 0 |
| payment_plan | 20/25 | 20/25 | 0 |
| earliest_date_for_full_payment | 16/25 | 17/25 | +1 |
| spending_changes_needed | 21/25 | 21/25 | 0 |

**Conclusion: evidence extraction's net effect on this sample is a wash.** It fixed all 4 axes on request_02
(a real message-driven salary raise applied correctly) and the amount on request_14, but it broke 3 axes on
request_11 (see root cause #1 below) — an almost exact cancellation. 21 of the 22 mismatching rows are
identical with or without evidence extraction, i.e. **the deterministic forecasting core, not evidence
extraction quality, is responsible for the large majority of the current error.** The one clear exception
(request_11) is a real evidence-handling bug, not noise — see below.

## Root cause per mismatch (22/25 rows; 01, 09, 16 exact)

Categories: 1=evidence extraction, 2=event lifecycle/state, 3=recurring expense estimation,
4=confirmed income timing, 5=cashflow simulation, 6=spending-change modeling, 7=plan selection, 8=other.

| Request | Wrong axes | Amount diff | Primary cause | Note |
|---|---|---:|:-:|---|
| request_02 | none | +1,107,626 (+6.4%) | 3 | Variable-expense mean estimate off; categorical axes all correct despite the amount gap |
| request_03 | none | +98,737 (+11.3%) | 3 | Same pattern, smaller scale |
| request_04 | none | **+2,207,486 (+26.3%)** | 3 | Largest error in the set; safety-critical (overestimate), but status/method/earliest still land right since "wait" targets a fixed date |
| request_05 | none | −737 | 3 | Trough at day 89 (near 90-day edge) — long-horizon estimate drift |
| request_06 | **all 5** | −79.46 | 3 (+6) | `('expense','transport','debit')` fit a 5-day grid (35 hits) on what looks like noisy irregular spending — likely an over-fit series inflating projected debits; the one in-window `stop` occurrence only recovers 19 of the streaming event's 57, not enough |
| request_07 | earliest | −933.35 (−1.1%) | 4 | `salary_date_change` message re-anchors one salary occurrence; re-fit grid lands the second projected installment cycle a month early |
| request_08 | status, method, plan, earliest | +0.63 (negligible) | 3 | Knife-edge case: income ≈ expenses over 90 days: a tiny estimate shift flips affordable_later↔not_affordable |
| request_10 | none | −12,700 | 3 | Trough at day 87, same long-horizon drift as request_05 |
| request_11 | **all 5** | −190,778 (−1.5%) | **1** | Message says "confirmed base salary is IDR 38,760,000," contradicting 5 months of settled `Base salary` events at 23,256,000. The fact-application layer overwrote the settled series unconditionally — this violates the spec's own conflict rule ("a settled event over an estimate") and is the one evidence-extraction bug in this set, not a forecasting error |
| request_12 | earliest, spending_changes | −4,793.75 (−7.4%) | 4 (+6) | `income_ended` zeroes a 3-hit "seasonal" salary series completely; gold's numbers imply a softer/partial cutoff |
| request_13 | status, method, plan, earliest | +57.40 (+13.2%) | 4 | Two separate salary series detected for one user (one stable, one "variable" and excluded); excluding the second under-counts income near the horizon edge, flipping a genuinely-safe case to "never safe" |
| request_14 | none | +18.55 | 3 | Minor estimate drift, no categorical effect |
| request_15 | none | −77.96 | 3 | Same, tiny absolute amount either way |
| request_17 | earliest | −825.90 (−0.34%) | 4 | Installment-cycle grid anchor lands one month later than gold's |
| request_18 | none | +84.05 | 3 | Minor drift |
| request_19 | payment_plan | −3,643.85 (−12.6%) | 3 | `partial_payment` split amounts follow amount_safe_to_pay directly, so this is the amount-estimation error surfacing in the plan field |
| request_20 | none | +3,569.68 | 3 | Large relative miss, no categorical effect (both not_affordable) |
| request_21 | status, earliest, spending_changes | +31.05 (negligible $) | 3 | **Safety-critical overestimate**: model says fully safe today with no changes; gold requires stopping/reducing two subscriptions — under-estimated variable spend near the trough |
| request_22 | none | −10.85 | 3 | Minor drift |
| request_23 | none | −791.82 (−8.6%) | 3 | Minor drift, larger scale |
| request_24 | none | +119.29 | 3 | Minor drift |
| request_25 | none | **−1,048,916.59 (−73.6%)** | 3 (flagged) | Second-largest error; no categorical effect (both not_affordable) but the magnitude at this IDR scale is disproportionate — worth a dedicated look before trusting the amount axis at large scale, separate from the general estimator tuning |

### Root cause tally

| Category | Count (primary) |
|---|---:|
| 1. Evidence extraction | 1 (request_11) |
| 3. Recurring expense estimation | 17 |
| 4. Confirmed income timing | 4 |
| 6. Spending-change modeling (secondary, alongside 3/4) | 2 |
| 2, 5, 7, 8 | 0 |

## What this means for next steps (not yet acted on, per instruction)

- The estimator tuning question from before is now better scoped: it should target the 17 "recurring expense
  estimation" rows, most of which are single-digit-to-low-double-digit percent misses plus two outliers
  (request_04 overestimate, request_25 under/overestimate at large scale) worth checking individually first.
- request_11's conflict-resolution gap (message vs. settled history) is a correctness bug in `forecast.py`'s
  `apply_facts`, independent of estimator tuning — recurring/temporary salary facts currently override the
  detected series unconditionally instead of checking it against actual settled history first.
- requests 07, 12, 13, 17 point to one shared mechanism: how salary series are split, re-anchored, or zeroed
  near the edges of the 90-day window and around message-driven changes — likely one fix location, not four
  separate ones.

No request-specific handling was added anywhere in `code/` to produce these numbers.
