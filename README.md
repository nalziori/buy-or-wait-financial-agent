# Buy or Wait? — Financial Affordability Agent

A personalized financial agent for the **HackerRank Orchestrate** hackathon (September 2026). Given a request like *"Can I afford this laptop?"*, it simulates 90 days of a user's cash flow and decides whether they should pay in full, pay partially, use installments, wait, or not proceed at all.

**Result:** 86th / 3,062 participants (top ~2.8%), final score 68.1 / 100. Chat transcript 9.6/10, AI judge interview 23.7/30, Output CSV 12.6/30, Code zip 22.2/30.

## Why this is interesting

Most of the effort here went into two things a naive point-estimate solution misses:

1. **Keeping the LLM out of the decision.** The model only does two things — read a payroll/receipt image when an amount is blank, and turn a free-text message into typed facts (salary change, income ended, one-time deposit, etc.). Every affordability number, date, and payment plan comes from deterministic Python. This satisfies the spec's determinism requirement and structurally blocks prompt injection: extracted text is parsed as candidate facts, never concatenated into a rule set.
2. **A calibrated safety margin instead of a better point estimate.** Every point-estimator swap tried (median, last-value, linear/damped trend, recent-window mean) traded MAE against a safety-critical overestimate rate — improving one number by making the system tell users they can safely spend more than they actually can. Conformal risk control breaks that trade-off: a safety margin (λ) is calibrated from a **leak-free backtest** built from each of 275 users' own historical settled cash flow (cut the last 90 days off their own history, forecast forward, compare against what actually happened — never touches any evaluation label), then shrunk per-currency toward the global value by sample size. This was the only change in the project that improved MAE *and* the safety-critical rate at the same time (MAE 187,281→165,765; overestimate rate 40%→20% on the 25 public samples).

## Architecture

```
data.py       Joins users, financial events, exchange rates, payment options
evidence.py   LLM calls — image amount extraction, message → typed facts (only place the LLM is used)
forecast.py   90-day cash-flow simulation + the calibrated safety buffer
planner.py    Payment-plan candidate generation, feasibility, tie-break ranking
main.py       Entry point — wires it together, writes output.csv
```

Full design rationale, the anti-overfitting discipline followed throughout (the 25 public samples are a debugging set, never a tuning target), and a decision-by-decision log are in [`CLAUDE.md`](./CLAUDE.md).

## Run it

```bash
export GEMINI_API_KEY=...
python3 code/main.py
```

No external dependencies beyond the Python standard library.

`output.csv` is written to the repository root. `code/cache/llm_cache.json` holds every LLM response this project ever produced — reruns against the same inputs cost zero new API calls.

## What's in this repo

- `code/` — the solution above
- `eval/` — evaluation harness, the conformal-calibration script (`lambda_calibration.py`), and per-iteration audit/experiment scripts
- `evaluation/` — write-ups: the amount_safe_to_pay root-cause research, an independent 30-request fresh-eyes disagreement audit, the token-usage/cost report
- `dataset/` — the organizer-provided input data
- `log.txt` — full development transcript (required submission artifact)
- `CLAUDE.md` / `AGENTS.md` — the project brief and eval-iteration log this was built against

## Judge feedback received (and what it changes)

The organizers sent written feedback on 2026-09-22. Summary, with how it maps onto this code:

| Area | Feedback | What I found in the code / next step |
|---|---|---|
| Output CSV | Rows that should be "affordable with a plan" or "affordable now" were marked not affordable; safe-to-pay was far from what the cash flow supports; spending changes and earliest payment date were often missing or mismatched. **Make one cash-flow forecast the single source of truth** for action, safe-to-pay, timing and spending changes. | `planner.decide` already derives everything from one forecast, so the main causes are (1) forecast error (local check: `amount_safe_to_pay` exact match 3/25), and (2) `amount_safe_to_pay` and `earliest` are computed *before* spending changes ([`planner.py:97-98`](code/planner.py)) while `affordable_with_plan` is decided *after* them ([`planner.py:120`](code/planner.py)), so those fields can disagree with the chosen plan. Next: recompute all four fields from the selected plan in one pass. |
| Code | A quota, timeout or malformed model response can stop the whole run. Add a deterministic fallback ("not enough evidence", conservative defaults, keep processing) and validate rows before writing. Consider a small planner/router so it behaves more like an agent; add few-shot examples for conflicting messages. | `llm.py` raises after retries and `main.py` has no per-request guard or output validation. Next: per-row try/except, a `validate(row)` check of cross-field rules before `output.csv` is written, conflict examples in the extraction prompt. |
| Chat transcript | Strong constraints and a rigorous verify loop. State the output contract and cross-field rules up front, explain module boundaries and approach choices before scaffolding, write down policies for missing or contradictory evidence, and paste raw stack traces when debugging. | Applies to the next build; the contract goes into `CLAUDE.md` before any code. |
| Interview | Answer first, then one concrete walk-through; explain numeric calibration as what the parameter does, where it lives, and how it was checked; be ready to point to files and functions and to end-to-end results. | Preparation habit, not a code change. |

These are not fixed in this repository yet; the submitted code is unchanged.

## Known, disclosed limitations

- One safety-critical overestimate (`request_04`, +2.2M in local currency) was investigated exhaustively — ruled out missing categories, recurrence detection, estimator choice, trend, and horizon-boundary effects — and left unresolved rather than special-cased for one request.
- EUR-currency requests sit at a 12.9% overestimate rate after calibration, above the 10% target; the small sample (n=62) gives EUR's own calibrated value a wide confidence interval, so pushing the correction further risked overfitting to noise.
- An independent 30-request audit (fresh subagent, no shared context, sampled from the unlabeled 250-request evaluation set) found a recurring weakness in interpreting salary/income-change messages. Diagnosed but not fixed — any correction based on unlabeled evaluation requests would be holdout leakage with no way to verify it actually helps.
