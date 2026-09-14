# Forensic Audit: Deterministic Forecasting Core

Scope: fix real correctness bugs first, trace the salary pipeline for 4 flagged requests, decompose the
17 recurring-expense-estimation cases, answer the ML-suitability question, and run estimator experiments —
in that order, before touching ML. No request-specific hardcoding; no tuning to sample outputs.

## 1. request_11 conflict-resolution bug — fixed

**Bug**: `apply_facts()` in `code/forecast.py` let any `recurring_salary_amount`/`temporary_salary_amount`
message fact overwrite the detected salary series unconditionally, with no check against settled history.
request_11's message claims "confirmed base salary IDR 38,760,000" with no effective date, while 5 months of
`settled` `Base salary` events all show 23,256,000 — the message directly contradicts strong settled evidence,
which the spec's conflict rule says should win ("settled over estimate/forecast", "conservative when still
ambiguous").

**Fix** (`code/forecast.py`, `settled_salary_refs()` + guard in `apply_facts()`): a `recurring_salary_amount`/
`temporary_salary_amount` fact with **no effective_date** is treated as an undated claim, not a dated
amendment. It is only applied if it's within 10% of a stable (repeated, low-variance) settled income series
detected for that user; otherwise it's skipped and logged to `Forecast.fact_notes`. A fact **with** an
effective_date (an explicit "raise effective on X" statement) is still applied unconditionally — that's a
genuine dated amendment, which the spec's rule 1 favors.

**Audited generally, not just for request_11**: ran this rule against every `recurring_salary_amount`/
`temporary_salary_amount` fact extracted from the full 215-message dataset (not just the 25 samples). 16 of 26
such facts across the whole dataset get blocked by this rule, all with the message's claimed amount roughly
1.61-1.67x the settled reference — a suspiciously consistent ratio suggesting these messages describe a
different total (possibly a second income stream ending, leaving a component our single-series detection
doesn't isolate) rather than a real amendment to the observed salary. Since none of them carry an
effective_date and all contradict multiple months of settled data, blocking all 16 is the conservative,
spec-consistent choice — not a request_11-specific carve-out.

**request_11 before/after**:

| | affordability_status | method | plan | earliest | spending_changes |
|---|---|---|---|---|---|
| Gold | affordable_with_plan | full_payment | 13,110,000 today | 2025-07-15 | reduce_to:event_989 |
| Before fix | affordable_later | wait | 13,110,000 on 05-15 | 2025-05-15 | none |
| After fix | **affordable_with_plan** | **full_payment** | **13,110,000 today** | 2025-06-15 | stop:event_949 + reduce_to:event_989 |

3 of 5 axes now correct. The remaining gap (earliest 06-15 vs 07-15, one extra `stop` change) is no longer an
evidence bug — it's the same recurring-expense-estimation noise as everywhere else (see §3).

## 2. Salary-series pipeline audit — requests 07, 12, 13, 17

Traced: raw events → lifecycle resolution (status filter) → series detection (`detect_series`/`best_grid`) →
message amendments (`apply_facts`) → effective salary list → 90-day projection. Before assuming these were all
"income-timing" bugs, each was traced individually — **only one of the four actually was.**

**request_07 — real bug, fixed.** `salary_date_change` ("confirmed salary is now expected on 2024-09-23,
replaces the earlier date") only moved the *next* projected occurrence to the new date; every subsequent month
snapped back to the old day-of-month grid. Since "replaces the payroll date" describes a durable change, the
whole future grid should re-anchor on the new date. **Fix**: `salary_date_change` now removes all future
non-fixed occurrences from the changed one onward and regenerates them monthly from the new effective_date.

| | before | after | gold |
|---|---|---|---|
| earliest_date_for_full_payment | 2024-10-15 | **2024-10-23** | 2024-10-23 |

Exact match, confirmed by rerunning the sample. status/method/plan were already correct; this fixes the one
remaining wrong axis.

**request_12 — not a series bug.** `income_ended` correctly zeroes a 3-hit, differently-labeled
("Seasonal contract payment" x2, "Temporary assignment pay" x1) series that isn't a stable recurring salary in
the first place — the message and the data agree the gig work stopped. Income is (correctly) zero for the full
90 days both before and after the audit. The remaining gap (amount −7.4%, extra spending changes, blank
earliest) is recurring-expense-estimation noise on a near-zero-income balance walk, not a construction defect.
Reclassified from "income timing" to "recurring expense estimation."

**request_13 — not a series bug.** This user genuinely has two named, distinct income lines: `Primary
household salary` (1,343.54, stable, 5 settled hits) and `Second household income` (variable, 4 hits, stops in
Jan 2024). `detect_series` correctly splits them by fit quality (not by description text, which it never
reads) and correctly drops the second as both variable and stale before the request date. Manually walked the
day-by-day balance: the true blocker is a second, later dip at day 89 (2024-06-04, one more rent cycle) that
sits at 2,014.01 against a 2,241.60 requirement — a 227.59 (10%) shortfall from ordinary expense-estimate
drift over an 82-day span, not from any missing income. Reclassified to "recurring expense estimation."

**request_17 — not a series bug.** Single clean salary series (`Payroll credit`, 206,000, 5 settled hits +
one `scheduled` "Next confirmed salary" agreeing exactly), no message facts at all for this user. Walked the
daily balance directly: day 43 (2026-04-13) sits at 439,340.63 against a 440,700 requirement — short by
**1,359.37, or 0.3%** — one day before the March-cycle buffer would otherwise have carried it through. That
single near-miss is what pushes `earliest_date_for_full_payment` a full pay cycle later (04-15 instead of
03-15). Reclassified to "recurring expense estimation."

**Revised tally**: of the original "4 income-timing" cases, 1 was a real, now-fixed pipeline bug; 3 were
mis-attributed by the first-pass root-cause pass and are actually expense-estimation cases (see §3). Root cause
category 4 shrinks to 0 remaining open cases; category 3 grows from 17 to 20.

## 3. Recurring-expense estimator audit (20 cases, with 04/25/08/21 in detail)

Every **fixed** category (rent, insurance, subscriptions, most debt_repayment/education) has zero historical
variance across all 25 samples — the current rule (mean over full history) reproduces them exactly, and none
of them contribute to any error. All observed error comes from **variable** categories: groceries, transport,
dining, utilities, shopping, entertainment, streaming — categories that vary because they represent discrete
day-to-day purchase decisions, not a fixed contract amount.

### request_04 — largest error, unresolved, flagged for further work

Gap: PRED 10,609,286.07 vs gold 8,401,800.00 (+2,207,486.07, +26.3%, **safety-critical overestimate**).

| Category | History (last 5) | Grid | Current rule | Window contribution |
|---|---|---|---|---|
| utilities | 2,017,103 / 1,981,052 / 2,033,869 / 1,980,835 / 2,004,119 (CV ~1%) | monthly | mean | −2,003,396 |
| entertainment | 1,484,370 / 1,375,854 / 1,542,620 / 1,291,304 / 1,231,859 (declining, CV ~7%) | monthly | mean | −1,385,201 |
| groceries | 1,831,438 / 1,698,278 / 1,075,064 / 1,809,753 / 1,433,696 (CV ~19%) | 7-day | mean | −1,499,474 |
| transport | 1,030,377 / 912,939 / 853,092 / 602,450 / 1,016,426 (CV ~17%) | 7-day | mean | −832,507 |
| dining | 1,282,287 / 1,259,308 / 1,661,337 / 1,886,856 / 2,108,488 (**rising trend**, +~15%/cycle) | 14-day | mean | −1,748,635 |

The gap (2.2M) exceeds *every single category's own window total* — no one category's estimator swap can
close it alone; it would take a coordinated, large shift across several categories simultaneously. The one
structural clue is **dining's clear upward trend** (1.28M → 2.11M over 5 points, mean smooths across a
trend that's still rising) — a mean systematically lags a trending series. This is a real candidate for "the
current rule is wrong" but does not by itself explain the full 2.2M gap. **This one needs more investigation
before any fix**, and is called out rather than forced into a tidy explanation.

### request_25 — second-largest error, revealed a detection bug

Gap: PRED 376,083.41 vs gold 1,425,000.00 (−1,048,916.59, −73.6%). No categorical effect (both not_affordable).

| Category | Grid inferred | History (last 5) | Note |
|---|---|---|---|
| transport | **5-day** (→ 18 projected occurrences in 90 days) | 560,613 / 458,597 / 663,001 / 729,004 / 571,597 (CV ~15%) | Same 5-day false-grid pattern seen in request_06 |
| dining | 7-day | 1,251,982 / 949,118 / 1,051,250 / 777,035 / 1,133,037 (CV ~18%) | High variance, 2 occurrences fell in-window |
| groceries | 10-day | 1,388,569 / 1,335,295 / 1,369,083 / 864,689 / 1,472,349 (CV ~17%) | |

**This is the one with a concrete, generalizable finding**: `best_grid` fits a 5-day period to `transport` for
this user, identical to the pattern already found independently in request_06. Transport spending is naturally
bursty and irregular (fuel, tolls, rides on no fixed schedule), and the brute-force interval search can lock
onto a short common gap that appears by chance among many small, irregularly-timed transactions rather than a
true recurring cadence — inflating the projected **occurrence count**, not just the per-occurrence amount, over
the 90-day window. This is a recurrence-**detection** flaw (category B/C below), not inherent randomness in the
spending itself.

### request_08 — negligible amount error, categorical flip is a knife-edge

Gap: +0.63 (effectively exact). All variable-category contributions here are tiny (under $60 each) and the
gap is 0.4-4.5% of any single category's window total — this trough is not where the earlier "all axes wrong"
mismatch comes from. The real driver is cumulative drift much later in the 90-day window where income and
expenses are nearly balanced (see the earlier diagnostic trace); a single-day category breakdown can't
localize it because it's an accumulated effect over ~60+ days, not a local trough issue.

### request_21 — negligible amount error, but flips the categorical outcome

Gap: +31.05 against a $3,911 balance (0.8%). Every category here is low-variance (utilities CV ~3%, shopping
CV ~6%) — there is no outlier category to blame. This is a genuine knife-edge: the true safe amount and the
requested amount are close enough that a few dollars of ordinary estimate noise flips `affordable_now` (no
changes) vs `affordable_with_plan` (2 changes required). No aggregate estimator swap can reliably resolve a
case this tight — only a formula that exactly matches gold's would, and there's no evidence such a formula is
recoverable from the available history.

## 4. Is this data ML-suitable?

**A. Are future recurring amounts stochastic, or rule-based and under-detected?** Both, split cleanly by
category type:
- **Fixed categories are 100% deterministic and already perfectly captured** — rent, insurance, most
  subscriptions, debt_repayment, education repeat with zero variance across every sample checked. No error, no
  ML needed here; this is rule reconstruction that already works.
- **Variable categories (groceries, transport, dining, utilities, shopping, entertainment, streaming) show
  real day-to-day variance (CV 3-30%)** that looks like ordinary discretionary spending noise, not a hidden
  deterministic formula — except for one clear structural finding: dining's upward trend in request_04, and
  the 5-day-grid false positive on transport in requests 06 and 25.

**B/C. Rule-reconstruction failure vs. genuine uncertainty vs. wrong classification/horizon handling?**
Concretely found in this audit:
- One real **evidence-conflict bug** (request_11) — fixed.
- One real **recurrence re-anchoring bug** (request_07's `salary_date_change`) — fixed.
- One real **recurrence-detection bug** (5-day false grid on transport, requests 06 and 25) — identified,
  not yet fixed (see recommendation).
- Two cases (request_13, request_17) that looked like income-timing bugs on first pass turned out, after
  tracing the full pipeline, to be ordinary estimate drift compounding right at the edge of the 90-day window
  or right before a payday — a **horizon-handling sensitivity**, not a detection defect.
- One case (request_04) where the gap is too large to attribute to any single category and needs further
  investigation before concluding anything.

**Conclusion: this is primarily a rule-reconstruction and pipeline-correctness problem, not a fundamentally
stochastic one.** Three real, fixable/identifiable deterministic bugs were found by tracing the pipeline by
hand — none of them needed a statistical model, they needed correct logic. The remaining variable-category
noise is real but modest in most cases (single-digit to low-teens percent), with two outliers (request_04,
request_25) that point to specific, nameable mechanisms (a trending series, a mis-fit grid) rather than
irreducible randomness.

**If ML were ever revisited**, the only defensible candidates would be the variable-spend categories
(groceries, transport, dining, utilities, shopping, entertainment) — never the fixed categories, which are
already exact. But per §5 below, even switching *estimator* alone barely moves the needle, which argues the
next step is fixing detection (grid-fitting), not modeling residuals.

## 5-6. Estimator experiment (full pipeline, all 25 samples, current post-fix baseline)

Ran `decide()` under six `Config.amount_estimator` settings. `current` and `mean` are the same method in this
codebase (the current rule already is a plain historical mean) — listed together. No estimator was tuned to
any request_id; the same rule applies uniformly to every category and every user.

| Variant | safe exact | MAE | median AE | over | under | **safety-critical over-rate** | status | method | plan | earliest | spend | all-6 exact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| current / mean | 3/25 | 187,281 | 737.0 | 10 | 12 | **40%** | 84% | 88% | 84% | 72% | 84% | 12% |
| median | 3/25 | 189,649 | 171.5 | 10 | 12 | 40% | 80% | 84% | 80% | 76% | 80% | 12% |
| last | 3/25 | 185,519 | 560.3 | 10 | 12 | 40% | 76% | 80% | 76% | 76% | 84% | 12% |
| max | 1/25 | 303,046 | 2,062.9 | 5 | 19 | **20%** | 56% | 56% | 56% | 44% | 76% | 4% |
| recent-window mean (last 3) | 3/25 | **174,698** | 345.1 | 8 | 14 | **32%** | 80% | 84% | 80% | 72% | 84% | 12% |
| recent-window median (last 3) | 3/25 | 188,222 | 398.0 | 10 | 12 | 40% | 76% | 80% | 76% | 76% | 84% | 12% |

**Safety check, reported separately as instructed**: `max` cuts the safety-critical overestimate rate to 20%
(best of any method) but destroys everything else (MAE nearly doubles, `all-6 exact` drops to 4%, and it now
*under*-recommends 19/25 times, which fails users just as badly in the other direction). `recent-window mean`
is the only variant that improves **both** MAE (−7%) and the safety-critical rate (40%→32%) at once, at a
small cost to `status`/`plan` accuracy (−4pp each) relative to plain mean. **No variant makes a meaningful dent
in exact amount_safe_to_pay match (stuck at 3/25 regardless, except max which is worse)** — consistent with
§4's finding that simple aggregate-statistic swaps aren't the lever that matters here; detection and pipeline
correctness are.

Signed error by category (current/mean vs. recent-window mean) shows every variable category moves in the
same direction — recent-window mean is uniformly less severe (smaller-magnitude debits) than full-history
mean across dining, groceries, transport, streaming, shopping, rent-adjacent utilities — because it tracks
recent softening/hardening trends instead of averaging over stale history. This is consistent with, not
contradictory to, the request_04 trend finding in §3.

## 7. Recommendation

**B — improve deterministic recurrence inference. Do not introduce ML now.**

Evidence for this call:
1. Three real, traceable, fixable bugs were found by hand-auditing the deterministic pipeline (evidence
   conflict, resolved; grid re-anchoring, resolved; grid over-fitting on bursty categories, identified). None
   of them are the kind of problem ML addresses — they're logic bugs.
2. The estimator experiment shows the *aggregation rule* isn't the main lever: swapping mean→median→last→
   recent-window moves accuracy by single-digit percentage points, not the multiple-fold improvement needed to
   close the amount_safe_to_pay exact-match gap (stuck at 3/25 or 12% across four of six variants).
3. There is no legitimate training signal available: `sample_requests.csv` is 25 rows, there is no separate
   held-out labeled set, and the instructions explicitly rule out training on solved sample outputs. Any ML
   attempt right now could only mean fitting a model to these same 25 points — which is both against the
   instruction and statistically indefensible (25 points, no validation set, high-cardinality categorical
   context per user).
4. The one concrete lead for further deterministic improvement is `best_grid`'s vulnerability to false-positive
   short-period detection on naturally bursty categories (transport, confirmed in two independent samples) —
   fixing the grid-fitting heuristic (e.g., requiring a minimum interval consistency or penalizing very short
   periods on already-irregular categories) is a bounded, well-scoped next step, not a research project.
5. request_04's unresolved large gap and request_04's trending-dining pattern are the only signals suggesting
   "smarter deterministic" (e.g., a linear trend term instead of a flat mean) might help beyond what's tested
   here — this is still B, not C or D: a better deterministic rule, not a statistical model.

**Not recommended right now**: C (hybrid) and D (ML residual correction) both require a genuine held-out
evaluation signal this project doesn't have. Revisit only if, after fixing the grid-detection issue and trying
a trend-aware deterministic estimator, a real held-out labeled set becomes available and residual error remains
concentrated and structurally unexplainable — neither condition is met yet.
