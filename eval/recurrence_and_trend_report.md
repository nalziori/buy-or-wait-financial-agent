# Recurrence Detection + Trend Estimation: Engineering Report

## 1. Old recurrence-detection behavior

`best_grid()` scored every candidate period purely on `hits - misses` (net grid matches), with no notion of
whether the underlying event timing was actually consistent, no penalty for short periods, and no floor on
how many observations were needed to trust the result. A period could win by explaining a bare majority of
events with zero structural sanity check.

## 2. New recurrence-detection rule

`score = (hits - misses - penalty + coverage, period == "monthly", anchor)`, where:
- `coverage = hits / total_events_in_group` — a small bonus for grids that explain more of the group.
- `penalty = 8.0 * cv * max(0, avg_gap/period_days - 1)` — a short period is only penalized when the group's
  **raw** event timing is itself irregular (`cv`, the coefficient of variation of consecutive-event gaps) and
  the candidate period is much shorter than the typical raw gap. A perfectly regular sequence (`cv=0`) pays
  no penalty regardless of period length, so a genuine high-frequency recurrence is never suppressed.
- `cv` is only computed when there are **≥4 raw gaps** (≥5 events). Below that, a coefficient of variation
  isn't statistically meaningful, so no penalty is applied and the rule falls back to plain hit-counting.

**Iteration note (kept in per the anti-overfitting log)**: the first version of this rule had no minimum-gap
floor and, when diffed against the old scorer across the **entire dataset** (2,787 recurring-series groups,
275 users — not just the 25 samples), flipped 9 income series from `monthly` to `~90 days`. All 9 turned out
to be 3-event series with a temporary pay gap (e.g. `Payroll before leave` → `Payroll after returning from
leave`, gaps `[31, 91]` days) — a monthly salary with a pause, not a real quarterly cadence. That's a
textbook case of a CV computed from too few points being misleading. Added the ≥5-event floor, re-ran the
same full-dataset diff, and it dropped to **zero** changed decisions anywhere. That's the version implemented.

**Would this be built without ever having seen the sample labels?** Yes — the failure mode (short-period grids
in bursty timing) is real and independent of what any of the 25 gold values say, and the fix that mattered
(the ≥5-event floor) was found by testing the rule dataset-wide, not by chasing a sample score.

## 3-4. request_06 and request_25 before/after

**Correction to the previous audit**: these were NOT false positives. Printing the raw transport transactions
for both users shows every single consecutive gap is **exactly 5 days** — 34/34 for user_06, 35/35 for
user_25, zero exceptions (`cv = 0.0`). `best_grid` matched 35/35 and 36/36 events with zero misses. This is a
genuine, perfectly regular 5-day recurring charge, not a coincidental alignment. The new rule's own printed
candidate scores confirm it: at `cv=0`, `period=5` wins by a wide margin over `monthly` (35 vs 2 net hits) and
the new penalty term is exactly `0` for both.

| | Before | After |
|---|---|---|
| request_06 transport | period=5, 35/35 hits | period=5, 35/35 hits (unchanged) |
| request_25 transport | period=5, 36/36 hits | period=5, 36/36 hits (unchanged) |

Neither sample's output changed at all from this fix. The earlier hypothesis that a "false 5-day grid" was
driving these two samples' errors is retracted; their residual amount error comes from ordinary variable-amount
estimation on a real high-frequency category, not from a detection defect.

## 5. request_04 divergence diagnosis

Built a full event-by-event reconciliation of the 90-day window (every day the balance actually changes, not
a padded 90-row table — most days have no event).

Gold's two disclosed checkpoints let us reconstruct two reference points on gold's own path: implied trough
balance = `min_balance + amount_safe_to_pay` = 30,686,600 + 8,401,800 = **39,088,400**, and the date the full
12,693,000 becomes safe (`earliest_date_for_full_payment`) = **2024-06-15**, which is the *same date our own
forecast independently lands on* — this axis was never wrong for this sample. That agreement is itself a
finding: gold's trajectory has the same *shape* as ours (same events landing on the same days), just offset
by a roughly constant amount early in the window.

| Day | Date | Items | Closing balance | Margin vs. gold's implied trough |
|---:|---|---|---:|---:|
| 0 | 06-04 | (opening) | 52,206,950.00 | +13,118,550.00 |
| 1 | 06-05 | utilities −2,003,395.62 | 50,203,554.38 | +11,115,154.38 |
| 4 | 06-08 | groceries −1,499,474.48 | 48,704,079.91 | +9,615,679.91 |
| 5 | 06-09 | gym −1,027,900.00, transport −832,507.41 | 46,843,672.49 | +7,755,272.49 |
| 6 | 06-10 | dining −1,748,635.07, music_subscription −332,500.00 | 44,762,537.42 | +5,674,137.42 |
| 7 | 06-11 | scheduled school fee −1,704,300.00 | 43,058,237.42 | +3,969,837.42 |
| 8 | 06-12 | delivery_membership −377,150.00 | 42,681,087.42 | +3,592,687.42 |
| **9** | **06-13** | entertainment −1,385,201.35 | **41,295,886.07** | **+2,207,486.07 (our trough)** |
| 11 | 06-15 | groceries −1,499,474.48, **salary +38,190,000.00** | 77,986,411.59 | +38,898,011.59 |

The margin column never crosses zero or reverses sign — it shrinks smoothly and monotonically from
+13.1M to +2.2M by the trough, meaning there is **no single identifiable day where a specific event causes a
sudden jump**; the gap is a constant, roughly proportional offset present from day 0 onward, not something
introduced partway through. This directly rules out "date placement" and "occurrence count" as the mechanism
(a wrong occurrence count would show up as a step change on the day that occurrence would/wouldn't fire).

**Checked and ruled out one by one**:
- **Category classification**: `user_04`'s full settled history has exactly 11 (status, type, category)
  combinations (rent, utilities, dining, entertainment, groceries, transport, salary, gym, music_subscription,
  delivery_membership, plus one scheduled education fee) — every one of them is already present in our
  forecast. No category is missing.
- **Recurrence detection**: none of this user's series triggered the Phase 1 penalty (all have low/zero CV);
  confirmed unaffected.
- **Historical window / estimator choice**: tested `mean`, `median`, `last`, and `max` (the most conservative
  possible per-category estimator) in isolation for this request. `max` closes only about half the gap
  (residual −1,126,569 of the original −2,207,486) — no per-category aggregate swap reaches gold's number, so
  this is not simply "our estimator constant is too low."
- **Trend handling**: `dining` shows a real upward trend (1.28M → 2.11M over 5 points) that a flat mean
  underweights, but the total trend-adjustable headroom across all variable categories in this window is
  nowhere near 2.2M.
- **Horizon boundary**: the trough (day 9) is nowhere near the 90-day edge; boundary effects (relevant to
  requests 05, 10, 13, 17 in the earlier audit) don't apply here.

**Conclusion**: no deterministic-rule mechanism available in this codebase explains the gap. Per the explicit
instruction not to force a fix, **request_04 is left unresolved.** The one honest, unverifiable hypothesis
worth naming: the spec text says to "forecast essential variable spending conservatively" (AGENTS.md §6.3),
which could imply gold applies a systematic upward adjustment to *essential* categories (groceries, transport,
utilities are this user's protected categories) beyond a plain historical average — but the quantitative
gap is far too large for a plausible conservative adjustment (even a full standard deviation applied to every
protected category only accounts for roughly 450,000 of the 2,207,486 gap). This is flagged as an open
question, not implemented as a rule, because it isn't evidenced strongly enough to generalize confidently.

## 6. Trend-estimator experiment (all 25 samples, uniform rule, no per-ID tuning)

| Estimator | safe exact | MAE | median AE | **safety-critical over-rate** | status | method | plan | earliest | spend | all-6 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mean (current) | 3/25 | 187,281 | 737.0 | **40%** | 84% | 88% | 84% | 72% | 84% | 12% |
| median | 3/25 | 189,649 | 171.5 | 40% | 80% | 84% | 80% | 76% | 80% | 12% |
| last | 3/25 | 185,519 | 560.3 | 40% | 76% | 80% | 76% | 76% | 84% | 12% |
| max | 1/25 | 303,046 | 2,062.9 | 20% | 56% | 56% | 56% | 44% | 76% | 4% |
| recent-window mean (last 3) | 3/25 | **174,698** | 345.1 | **32%** | 80% | 84% | 80% | 72% | 84% | 12% |
| recent-window median (last 3) | 3/25 | 188,222 | 398.0 | 40% | 76% | 80% | 76% | 76% | 84% | 12% |
| linear trend | 3/25 | 183,415 | 315.6 | **44% (regression)** | 84% | 88% | 84% | 72% | 84% | 12% |
| damped trend (φ=0.7) | 3/25 | 186,300 | 696.8 | 40% | 80% | 84% | 80% | **80%** | 84% | 12% |

**Safety check applied as instructed**: `linear_trend` has the second-best median AE (315.6) but *increases*
the safety-critical overestimate rate from 40% to 44% (11/25 vs 10/25) — **treated as a regression and
rejected**, regardless of its MAE/median improvement. `max` gets the safety rate down to 20% but at the cost of
destroying every other metric (under-recommends 19/25 times, `all-6` drops to 4%) — also rejected, for the
opposite failure mode. `recent_window_mean` is the only variant improving *both* MAE and the safety rate
simultaneously, at a real cost of −4pp on two categorical axes. `damped_trend` is the only variant that
improves a categorical axis (earliest +8pp) while staying exactly safety-neutral.

**Rotating holdout (5 rounds of 20-dev/5-holdout, membership fixed before any round was scored)**: results are
dominated by noise at this sample size — `dev_safety_over%` and `holdout_safety_over%` swing between 20% and
80% round to round for every single variant, with no estimator consistently outperforming another across
rounds. This is reported as a sanity check only, per instruction, not as evidence of generalization; it did
not change the recommendation.

**No estimator materially closes the amount_safe_to_pay exact-match gap** — `safe_exact` is 3/25 for every
variant except `max` (worse). This confirms §4 of the prior audit: the bottleneck is not which aggregate
statistic is used.

## 7. 25-sample before/after (recurrence-detection fix)

Identical in every column — the fix changed zero decisions on this dataset (see §2). No table needed beyond
confirming: `safe_exact 3/25, MAE 187,280.8, status 84%, method 88%, plan 84%, earliest 72%, spend 84%,
all-6 12%`, both before and after.

## 8. Safety-critical overestimation rate before/after

Recurrence-detection fix: 40% → 40% (unchanged, as expected from §7).
Estimator experiment: see the bolded column in §6 — `recent_window_mean` is the only variant that improves it
(40%→32%); everything else is flat or worse.

## 9. Exact files/functions changed this round

- `code/forecast.py`:
  - `best_grid()` — rewrote the scoring function (coverage bonus + interval-consistency penalty).
  - `interval_dispersion()` — new; computes typical gap and CV, gated at ≥5 events.
  - `SHORT_PERIOD_PENALTY`, `MIN_GAPS_FOR_DISPERSION` — new module constants.
  - `estimate()` — added `linear_trend` and `damped_trend` options (used only in the experiment, not wired
    into the production `Config` default, which is still `"mean"`).
  - `trend_slope()` — new helper (OLS slope).
- `eval/estimator_experiment.py` — added the two trend variants and the rotating-holdout report.
- No changes to `code/planner.py`, `code/evidence.py`, `code/llm.py`, or the request_11/request_07 fixes from
  the previous turn (untouched, as instructed).

## 10. Recommendation for the next step

**Keep the recurrence-detection fix (already merged); do not change the production amount estimator; leave
request_04 open.**

- The recurrence-detection rule is real, general, evidenced across the full 275-user dataset, and costs
  nothing (zero regressions, zero current-dataset effect) — worth keeping as a defensive improvement for data
  this specific dataset doesn't happen to exercise.
- No estimator variant clears the bar of a **material, broad, safety-respecting** improvement:
  `recent_window_mean` is the closest (better MAE, better safety rate) but trades away 2 categorical axes;
  `damped_trend` gains one axis at flat safety; `linear_trend` fails the explicit safety check outright. None
  of these is a clear enough win to justify moving off `mean` for the production default, and switching based
  on a 25-point comparison the instructions explicitly frame as anti-overfitting terrain would be exactly the
  kind of overfit this process is designed to prevent.
- request_04's gap survived every mechanism checked (category coverage, estimator choice, trend, horizon,
  recurrence detection) — reporting it unresolved rather than inventing a rule to close it, per instruction.

**Answering the required counterfactual** for every change made this round: "Would I still make this change if
the 25 sample ground-truth values had never been shown to me?" — Yes for the recurrence-detection fix (found
and validated via dataset-wide diffing, not sample score-chasing). No for every estimator swap tested in
Phase 4 (none is justified as a standalone general principle; all were tested only because a gap was already
known) — consistent with rejecting all of them for production use.
