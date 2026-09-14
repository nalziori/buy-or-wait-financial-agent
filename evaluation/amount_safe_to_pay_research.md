# amount_safe_to_pay research (deterministic cashflow reconstruction)

Scope: R&D only, no production change unless Phase 8 = A. No ML. Uses cached gemini-3.5-flash
facts already on disk (`code/cache/llm_cache.json`) — zero new API calls this round. 25 public
samples are used only for diagnosis/regression, never as a training target.

Scripts: `eval/reconcile_safe_to_pay.py` (Phase 1/2 trace), `eval/test_safe_to_pay_formula.py`
(Phase 3 synthetic audit), ad-hoc one-off checks quoted inline below (Phase 2 currency check,
Phase 6 recurrence-confidence check).

## 1. Baseline metrics (unchanged from the prior round, re-verified)

| metric | value |
|---|---|
| amount_safe_to_pay exact match | 3/25 |
| MAE | 187,281 |
| median absolute error | 737 |
| safety-critical overestimate (pred > gold) | 10/25 (40%) |

## 2. Component-level decomposition

The formula actually implemented (`Forecast.safe_on(0)` in `code/forecast.py`, called from
`planner.decide`) is exactly:

```
amount_safe_to_pay = clip( min(day-by-day balance over 90 days) - minimum_balance_to_keep, 0, requested_amount )
```

`safe_on(0)` takes the min over the *entire* remaining horizon, not just up to a first local dip —
confirmed both by reading the code and by `test_earliest_full_payment_never_exceeds_the_true_horizon_max`
in Phase 3. This means `amount_safe_to_pay` is a genuinely global quantity: one bad event anywhere in
the 90 days can suppress it, by design (spec: "must never fall below minimum_balance_to_keep after any
projected essential expense... within the recommended plan").

Full per-request trace (bottleneck date, margin, and top-3 contributors both in a ±7-day window around
the bottleneck and cumulatively from day 0 to the bottleneck) is in the raw output of
`eval/reconcile_safe_to_pay.py`. Summary table, with **relative error = abs_err / current_available_balance**
added — this is the fair cross-currency comparison metric; raw absolute error is dominated by currency
denomination (IDR/KRW-scale users have amounts ~1,000x larger than INR/USD-scale users, which otherwise
makes absolute MAE misleading):

| request | pred | gold | signed err | rel. err (% of balance) | bottleneck offset (days) |
|---|---:|---:|---:|---:|---:|
| 01 | 25,256 | 25,256 | 0 | 0.00% | 13 |
| 02 | 18,336,765 | 17,229,139 | +1,107,626 | 1.83% | 13 |
| 03 | 971,737 | 873,000 | +98,737 | 1.70% | 13 |
| 04 | 10,609,286 | 8,401,800 | +2,207,486 | **4.23%** | 13 |
| 05 | 0 | 737 | -737 | 1.59% | 13 |
| 06 | 523.84 | 603.30 | -79.46 | **4.09%** | 13 |
| 07 | 86,237 | 87,170 | -933 | 0.43% | 13 |
| 08 | 285.20 | 284.57 | +0.63 | 0.04% | 13 |
| 09 | 166.61 | 166.61 | 0 | 0.00% | 25 |
| 10 | 0 | 12,700 | -12,700 | 1.69% | 13 |
| 11 | 12,319,867 | 12,510,645 | -190,778 | 0.30% | 13 |
| 12 | 60,370 | 65,164 | -4,794 | 2.48% | 13 |
| 13 | 490.80 | 433.40 | +57.40 | 2.06% | 13 |
| 14 | 616.29 | 597.74 | +18.55 | 0.47% | 13 |
| 15 | 5.09 | 83.05 | -77.96 | **4.40%** | 13 |
| 16 | 122,500 | 122,500 | 0 | 0.00% | 13 |
| 17 | 243,024 | 243,850 | -826 | 0.15% | 13 |
| 18 | 546.05 | 462.00 | +84.05 | **3.38%** | 13 |
| 19 | 25,176 | 28,820 | -3,644 | 1.83% | 13 |
| 20 | 8,969.68 | 5,400 | +3,570 | **3.48%** | 13 |
| 21 | 1,574.40 | 1,543.35 | +31.05 | 0.79% | 12 |
| 22 | 464.61 | 475.46 | -10.85 | 0.96% | 13 |
| 23 | 8,360.18 | 9,152 | -791.82 | 1.52% | 13 |
| 24 | 13,539.29 | 13,420 | +119.29 | 0.14% | 13 |
| 25 | 376,083 | 1,425,000 | -1,048,917 | **3.27%** | 13 |

Two findings that revise the initial (rejected) hypothesis:

1. **The bottleneck offset is ~13 days after request_date for 24/25 requests, regardless of user,
   currency, or category mix.** This is a structural artifact of most users' monthly rent/salary cycle
   (the low point sits right before the next payday), not a per-request anomaly — it means the "trough"
   is not a special date each user's data happens to have a bug on; it is the same calendar position
   every month for every user. No evidence of a bottleneck-placement defect.
2. **Absolute error is dominated by currency scale, not error concentration.** My first pass (looking
   only at absolute error) would have flagged request_04/25/02 as an "error-concentration" problem
   worth chasing (93% of total absolute-error mass). Converting to relative error (% of balance) shows
   this is **false** — those three are IDR-currency users whose balances are ~1,000x larger in raw units
   than INR/USD users, not requests, that are unusually broken. Relative error across all 25 sits in a
   fairly flat 0–4.4% band with no outlier group. I am flagging this because it was a live risk of
   over-fitting to the wrong metric (chasing "biggest number" instead of "biggest relative error"), which
   the anti-overfitting protocol explicitly warns against generalizing from.

## 3. Bottleneck analysis

Because the bottleneck date is essentially fixed (day 13, a monthly cyclical low), the question
"is the error a single wrong event or accumulated drift?" resolves cleanly: for every request, the
cumulative-to-bottleneck top-3 contributors and the local ±7-day-window top-3 contributors overlap
heavily (same 2–3 categories: rent/groceries/utilities/debt_repayment appear in both lists for all 25
requests — see script output). There is no case where a single unrelated or misplaced event appears
only in the local window and not in the cumulative view, or vice versa. **All 25 errors are explained
by accumulated drift across several recurring categories over the ~2-week window, not by a single wrong
event, wrong count, or misplaced date.** This rules out root-cause categories B (income timing), C
(expense occurrence count), E (expense date placement), and F (event inclusion/exclusion) as the driver
for any of the 25 — those would produce a step change concentrated on one event, which is not observed
anywhere in this batch.

## 4. Formula audit (Phase 3)

`eval/test_safe_to_pay_formula.py` — 8 synthetic, hand-computed cases, independent of the 25 samples:

* single future debit → correct margin
* balance already breached → clips to 0, never negative
* day-0 event is included in day-0's balance (not silently dropped as "not yet future")
* a later credit does not rescue an earlier trough (global min, not last-value)
* horizon is exactly 90 calendar days starting on request_date (day 0..89)
* `earliest_full` returns `request_date` when already safe
* `earliest_full` returns `None` when the requested amount is never safe anywhere in the horizon
  (not some arbitrary later date) — this one initially exposed a wrong *expectation* in my own test,
  not a code bug: I had assumed a post-trough balance rise that the scenario didn't actually contain.
  Rewrote the test with an explicit later credit once traced through by hand.
* `earliest_full` correctly waits for a later credit to actually land before calling a bigger amount safe

All 8 pass. Also confirmed by code inspection (not synthetic, since it requires real event statuses):
cancelled/failed events are excluded automatically because `build_forecast` only admits
`status in ("pending", "scheduled")` for one-off items and `status == "settled"` for series detection —
there is no separate exclusion list to audit, and no path exists for a cancelled/failed row to enter the
forecast. `amount_safe_to_pay` is computed before `change_candidates`/`cheapest_changes` are even called
(spending changes only affect plan feasibility downstream, never the base safe amount) — matches spec
("before optional spending changes"). No formula-level bug found this round.

## 5. Experiment matrix

Only one new experiment was warranted this round (see rationale below): **recurrence-count confidence
fallback** (Phase 6, idea 3) — checking whether series that just barely clear the detection threshold
(`min_nday_hits=3` / `min_monthly_hits=2`) are the ones driving the residual error, which would justify
falling back to a more conservative treatment for weakly-supported grids.

Ad-hoc check across all 25 forecasts: only request_14 and request_15 contain a series at the minimum
support threshold (both `('salary', 2, 'monthly')`). Their relative errors are 0.47% and 4.40%
respectively — one of the *lowest* and the single *highest* in the batch. There is no correlation between
weak recurrence support and error magnitude, and the highest-error requests (04, 06, 15, 18, 20, 25) have
**zero** weakly-supported series between them — their detected series are all well above threshold. This
falsifies the hypothesis before writing any code change, so no code change was made.

The other Phase 6 candidates (conservative variable-spend bound, bottleneck-aware local refinement,
constant-offset diagnosis) are not re-run here because the bottleneck analysis in §3 already rules out
their preconditions: there is no local single-event defect to refine around (bottleneck-aware refinement
needs one), and §2's relative-error finding rules out a request_04-specific constant offset as a general
phenomenon (it's the single largest relative-error case, but 06/15/18/20 are close behind it with no
shared structural cause — treating 04 specially would be exactly the forbidden per-request exception).
The prior round (`eval/estimator_experiment.py`, documented in `eval/recurrence_and_trend_report.md`)
already exhaustively tested "better historical-window selection" (mean/median/last/recent-window
mean+median/linear trend/damped trend) through the full pipeline with the safety-critical check applied;
re-running it here would be repeating a settled experiment for its own sake, not new evidence.

| hypothesis | change made | result |
|---|---|---|
| weakly-supported recurrence grids drive the residual error | none (falsified pre-code) | no correlation found; rejected |

## 6. Safety-critical analysis

40% overestimate rate is unchanged. §2/§3 show the errors are small (0–4.4% of balance), driven by
ordinary month-to-month variance in recurring variable-expense categories (groceries, dining, transport,
utilities) accumulating over a fixed ~2-week structural window, not by any traceable code defect. The
previous round already showed that every deterministic estimator alternative that reduces MAE either
leaves the overestimate rate unchanged or makes it worse (`linear_trend`: 40%→44%, rejected). Nothing in
this round's decomposition surfaces a new estimator or structural change that would improve the rate
without the same trade-off, since no estimator-level fix is implicated in the first place (§3).

## 7. Best candidate result

None. The recurrence-confidence experiment was falsified before implementation; no other candidate had
a supported precondition after the decomposition. No candidate reached the bar for adoption.

## 8. Regressions

None — no production code was changed this round.

## 9. Final recommendation

**Phase 8 outcome: C — no meaningful deterministic improvement found this round**, bordering on D for
the specific residual band (0–4.4% of balance, spread across ordinary variable-spend categories with no
shared structural fingerprint across the highest-error requests). The counterfactual test applies
cleanly here too: none of these findings depended on seeing the ground truth beyond computing the error
column itself — the bottleneck-offset regularity, the currency-scale artifact in raw MAE, and the
recurrence-confidence null result would all be exactly the same without the 25 labels.

## 10. Should production code change?

**No.** Keep `code/forecast.py` and `code/planner.py` exactly as they are. The two new files this round
(`eval/reconcile_safe_to_pay.py`, `eval/test_safe_to_pay_formula.py`) are diagnostic-only additions under
`eval/`; nothing under `code/` was touched.
