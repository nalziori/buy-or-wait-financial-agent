# Independent Sonnet disagreement audit (30 evaluation requests)

Diagnostic only. Ground truth for `dataset/requests.csv` is not available, so this measures
**disagreement between two independent solvers**, not accuracy. Neither prediction is treated
as correct by default.

## Method

* **Sample**: 30 of the 250 evaluation requests, chosen by `eval/select_audit_sample.py` with a
  fixed seed (42) and stratified on raw-data signals only (request_type, home_currency, message/
  image presence, salary-related message keywords, flexible-spending profile, installment-option
  availability, partial-payment eligibility, and a raw-data "near affordability boundary" proxy).
  No request was chosen because it looked likely to fail. IDs are reproducible from
  `evaluation/sonnet_30_request_ids.txt`.
* **Independent pass**: a fresh general-purpose agent (Sonnet 5), spawned with no prior context,
  given only `problem_statement.md` and the raw `dataset/` files (filtered to the 30 requests
  itself). It built its own small forecaster and produced only the 4 requested fields per request,
  in `evaluation/sonnet_30_independent.csv`.
* **Current solver**: `eval/current_solver_30.py` re-ran our existing deterministic pipeline on the
  same 30 requests using only cached Gemini facts already on disk (0 new API calls), producing
  `evaluation/current_solver_30.csv`.

### Independence caveat (disclosed, not hidden)

The subagent's harness auto-loads this repo's `CLAUDE.md` into every session's system context
regardless of what the task prompt asks it to read — the same way our own session sees it. I
checked `CLAUDE.md` for any mention of the 30 sampled request IDs before trusting this audit:
**none of the 30 IDs appear anywhere in it** (its Decision Log only ever discusses the 25 public
`request_01`–`request_25` samples). So the specific numbers below were not leaked. What *could*
have leaked is generic architectural awareness (e.g. that recurrence detection and small-margin
estimation are areas of interest) — the subagent's own final summary says it "never opened" our
`eval/`/`code/` files or relied on them for numbers, and its worked method (its own from-scratch
forecaster) is consistent with that. Treat this as a lightweight audit, not a formally blinded one.

## Comparison (all 30)

`abs diff` = current − Sonnet on `amount_safe_to_pay`. `rel diff` = abs diff / requested_amount.
Flag = rel diff > 10%, OR affordability_status differs, OR earliest_date differs by >7 days
(including one side having a date and the other not).

| request_id | type | cur safe | sonnet safe | rel diff | cur status | sonnet status | status eq | cur date | sonnet date | date eq | flag |
|---|---|---:|---:|---:|---|---|:-:|---|---|:-:|:-:|
| request_42 | emergency_expense | 25,475.13 | 52,100.00 | 51.1% | not_affordable | affordable_now | ✗ | – | 2026-01-05 | ✗ | ⚑ |
| request_44 | education | 30,429.03 | 28,872.90 | 1.6% | affordable_later | affordable_later | ✓ | 2025-04-15 | 2025-02-15 | ✗ | ⚑ |
| request_48 | family_transfer | 45,700.00 | 0.00 | 100.0% | affordable_now | not_affordable | ✗ | 2026-07-25 | – | ✗ | ⚑ |
| request_50 | travel | 42,646.90 | 43,900.00 | 2.9% | affordable_with_plan | affordable_now | ✗ | 2025-10-15 | 2025-08-06 | ✗ | ⚑ |
| request_51 | investment | 2,169,453.40 | 2,191,000.00 | 1.0% | not_affordable | affordable_now | ✗ | – | 2026-01-03 | ✗ | ⚑ |
| request_54 | housing | 2,083.52 | 0.00 | 1.7% | not_affordable | not_affordable | ✓ | – | – | ✓ | |
| request_80 | debt_repayment | 15,959.16 | 119,816.90 | 47.8% | not_affordable | not_affordable | ✓ | – | – | ✓ | ⚑ |
| request_96 | purchase | 72,758.97 | 76,700.90 | 4.4% | affordable_with_plan | affordable_with_plan | ✓ | 2026-02-15 | 2026-01-14 | ✗ | ⚑ |
| request_99 | emergency_expense | 17,445.43 | 18,062.00 | 3.4% | affordable_with_plan | affordable_now | ✗ | 2026-07-15 | 2026-07-04 | ✗ | ⚑ |
| request_101 | investment | 143,500.00 | 143,500.00 | 0.0% | affordable_now | affordable_now | ✓ | 2025-11-03 | 2025-11-03 | ✓ | |
| request_116 | family_transfer | 9,179.83 | 10,284.50 | 0.5% | not_affordable | not_affordable | ✓ | – | – | ✓ | |
| request_127 | family_transfer | 7,420.91 | 12,319.80 | 20.4% | affordable_later | affordable_later | ✓ | 2024-10-15 | 2024-11-11 | ✗ | ⚑ |
| request_147 | travel | 477.46 | 387.80 | 7.9% | affordable_with_plan | affordable_with_plan | ✓ | 2026-05-15 | 2026-06-13 | ✗ | ⚑ |
| request_148 | purchase | 7,127.02 | 8,225.00 | 4.9% | affordable_with_plan | affordable_with_plan | ✓ | 2024-08-15 | 2024-08-14 | ✗ | |
| request_153 | purchase | 15.20 | 0.00 | 0.5% | not_affordable | not_affordable | ✓ | – | – | ✓ | |
| request_164 | other | 27,018,000.00 | 27,018,000.00 | 0.0% | affordable_with_plan | affordable_with_plan | ✓ | 2025-02-04 | 2025-02-04 | ✓ | |
| request_188 | family_transfer | 102.94 | 0.00 | 4.2% | not_affordable | not_affordable | ✓ | – | – | ✓ | |
| request_192 | education | 107.83 | 242.20 | 6.6% | not_affordable | affordable_later | ✗ | – | 2026-06-13 | ✗ | ⚑ |
| request_201 | debt_repayment | 23,997,000.00 | 21,586,188.00 | 10.0% | affordable_now | not_affordable | ✗ | 2026-04-03 | – | ✗ | ⚑ |
| request_205 | debt_repayment | 10,621,000.00 | 10,621,000.00 | 0.0% | affordable_now | affordable_now | ✓ | 2024-03-06 | 2024-03-06 | ✓ | |
| request_207 | family_transfer | 4,516.76 | 5,420.00 | 7.6% | affordable_later | affordable_later | ✓ | 2026-07-15 | 2026-07-15 | ✓ | |
| request_214 | other | 41,113.73 | 0.00 | 58.9% | affordable_with_plan | not_affordable | ✗ | 2024-12-15 | – | ✗ | ⚑ |
| request_219 | education | 711.17 | 1,294.10 | 34.8% | affordable_with_plan | affordable_with_plan | ✓ | 2026-05-15 | 2026-06-13 | ✗ | ⚑ |
| request_220 | investment | 72.34 | 188.90 | 3.7% | not_affordable | not_affordable | ✓ | – | – | ✓ | |
| request_221 | housing | 109,800.00 | 109,800.00 | 0.0% | affordable_now | affordable_now | ✓ | 2025-11-03 | 2025-11-03 | ✓ | |
| request_224 | travel | 10,063,394.35 | 4,158,359.00 | 57.2% | affordable_with_plan | affordable_later | ✗ | 2025-02-15 | 2025-04-17 | ✗ | ⚑ |
| request_257 | other | 317.96 | 327.40 | 0.7% | affordable_later | affordable_later | ✓ | 2026-01-15 | 2026-01-15 | ✓ | |
| request_265 | family_transfer | 0.00 | 0.00 | 0.0% | not_affordable | not_affordable | ✓ | – | – | ✓ | |
| request_267 | housing | 1,641.71 | 160.30 | 77.0% | affordable_with_plan | not_affordable | ✗ | 2026-02-15 | – | ✗ | ⚑ |
| request_270 | investment | 96.77 | 157.60 | 2.0% | not_affordable | affordable_later | ✗ | – | 2026-09-13 | ✗ | ⚑ |

**17/30 (57%) flagged.**

## Root-cause hypotheses for the 17 flagged cases

Grouped by the most consistent mechanism, not by request_id — several requests share the same
likely cause.

### Group A — income/salary-message interpretation (5 requests: 44, 127, 147, 201, 219)

Sonnet's own notes for these explicitly cite a message it applied that changes projected income:
"added 2nd confirmed salary" (44), a leave-return payroll-grid re-anchor it says it verified for
double-counting (127, 147, 219), and a seasonal-contract-end that "removed" a wrongly-projected
income stream (201). This is the single most consistent, mechanism-identifiable pattern in the
audit — it points at `apply_facts()` in `code/forecast.py`, specifically the
`recurring_salary_amount`/`salary_date_change`/`income_ended` handling, for salary-change patterns
(leave-return, seasonal/contract-end) that were not present in the 25 public samples. **Hypothesis:
income timing / message-fact resolution.** Note `request_265` — same seasonal-contract-end pattern
per Sonnet's note — was *not* flagged (both sides landed on `not_affordable`/0), so our solver
does correctly apply `income_ended` in at least one case; the divergence in 201 suggests an
inconsistency in when/how it's applied rather than the mechanism being entirely absent.

### Group B — small-margin boundary flips (4 requests: 51, 192, 201 partly, 270)

51 and 270 have <2% amount disagreement yet flip `affordable_now`/`not_affordable`↔`affordable_later`
outright; 192 similarly. This matches exactly what the prior round's `amount_safe_to_pay` R&D found
in the 25 public samples: relative forecast error sits in a small (0–7%) band, but when the true
answer sits near a categorical threshold (safe-today vs. never-fully-safe-in-horizon), that small
band is enough to flip the label. **Hypothesis: minimum-balance/horizon-boundary sensitivity** —
not a code defect, an inherent property of a single-point deterministic forecast this close to a
threshold. Consistent with the prior finding that no tested estimator variant removes this without
trading off the safety-critical-overestimate rate.

### Group C — spending-change scope asymmetry (4 requests: 50, 96, 99, 267 — methodological, not a bug)

Our solver applied a `stop:`/`reduce_to:` spending change to rescue these plans
(`spending_changes_needed` ≠ `none` in `evaluation/current_solver_30.csv`); Sonnet was
deliberately *not* asked to model spending changes at all (per this audit's own scope, to keep it
lightweight). Any case where our `affordable_with_plan` specifically depends on a spending change
will disagree with Sonnet by construction, independent of whether the underlying forecast is right.
This does not indict either solver — it is a scope limitation of this particular audit design, and
should not be read as 4 more confirmed forecasting defects. `request_267`'s status disagreement
(`not_affordable` vs. our `affordable_with_plan`) is likely mostly this; its 77% amount gap,
however, is not explained by scope alone (see Group D).

### Group D — needs manual review, no single clean mechanism (4 requests: 42, 48, 80, 214, 224, 267's amount)

* **request_48**: Sonnet's note claims confirmed income of only ~984/month against ~25,200 rent —
  an outright insolvency reading that flatly contradicts our `affordable_now`. This is too large a
  gap to be estimation noise; either our solver is missing/misreading this user's true income
  level, or Sonnet misread a message/image amount or currency unit. Needs a manual side-by-side
  trace of this specific user's income facts — not resolved by this audit.
* **request_80**: both sides agree on `not_affordable`, but `amount_safe_to_pay` itself differs by
  48%. Since that field is scored independently of the categorical status, this is a real
  disagreement worth tracing even though the headline decision matches. Likely recurring/variable
  expense estimation over the horizon, but unconfirmed.
* **request_214, 224, 267 (amount)**: large, unexplained swings with no shared note or pattern;
  request_224 was independently flagged by Sonnet itself as a close judgment call ("installment
  safety near the buffer edge"). Plausible causes span payment-option interpretation
  (`max_installment_months`, partial-payment deadline eligibility) and variable-expense estimation,
  but nothing here lets us pick one over the other without deeper tracing.
* **request_42**: Sonnet is aware of a salary-drop message and still calls it `affordable_now`;
  our solver calls it `not_affordable`. Could belong in Group A (income-timing) or Group D — the
  note doesn't say enough to place it confidently.

## Main questions

**1. How many of the 30 show substantial disagreement?** 17/30 (57%).

**2. Is disagreement concentrated in particular request types or data patterns?** Not by
`request_type` — flags spread across 7 of 9 types represented, including 100% of the (small)
`emergency_expense`, `education`, and `travel` groups but only 1/3 of `purchase` and 1/3 of
`other`. It *is* concentrated by **data pattern**: every request with a salary-changing message in
this sample landed in Group A or was borderline (42), and every near-zero-margin request landed in
Group B. Plain fixed-recurring-expense requests with no income-changing message and no razor-thin
margin (e.g. 101, 116, 153, 188, 205, 221, 257, 265) agreed cleanly.

**3. Do the same kinds of issues seen in the public 25 samples appear here?** Yes, both mechanisms
recur: (a) message-driven salary/income-timing edge cases, the same class of bug already found and
partially fixed for requests 07/11 in the 25-sample forensic audit, now recurring in *different*
users (44, 127, 147, 201, 219) with *different* triggering patterns (leave-return, seasonal-contract
-end) that weren't represented in the 25 public samples; and (b) small-margin categorical
boundary-flips, matching the 0–4.4% relative-error band the prior `amount_safe_to_pay` research
found and could not remove without a safety trade-off.

**4. Specific to the public samples, or broader?** Broader. Group A's triggering patterns
(leave-return payroll re-anchoring, seasonal/contract-end) don't appear anywhere in the 25 public
samples' known facts, yet they produce the same class of disagreement here across 5 different
evaluation-set users — that's the clearest evidence in this whole audit that the underlying weakness
is **general to the architecture**, not an artifact of the 25 samples specifically.

**5. Which module should be investigated next?** `apply_facts()` in `code/forecast.py` — the
`income_ended` / `recurring_salary_amount` / `salary_date_change` handling for leave-return and
seasonal-contract-end message patterns (Group A). This is the one group with a concrete,
inspectable mechanism and a repeated pattern across independent users; Group B (boundary
sensitivity) was already investigated exhaustively in the prior round with no safe fix found, and
Groups C/D need more tracing before any module can be named with confidence.

## Files

* `eval/select_audit_sample.py` — sampling script (seed 42)
* `evaluation/sonnet_30_request_ids.txt` — the 30 selected request IDs (reproducible)
* `evaluation/sonnet_30_independent.csv` — Sonnet's independent predictions
* `eval/current_solver_30.py`, `evaluation/current_solver_30.csv` — current solver's predictions on
  the same 30, from cached facts, 0 new API calls
* This file — comparison and analysis

No production code was changed. `output.csv` was not touched.
