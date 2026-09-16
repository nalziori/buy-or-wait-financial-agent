# Buy or Wait? — Financial Affordability Agent

A personalized financial agent for the **HackerRank Orchestrate** hackathon (September 2026). Given a request like *"Can I afford this laptop?"*, it simulates 90 days of a user's cash flow and decides whether they should pay in full, pay partially, use installments, wait, or not proceed at all.

**Result:** 86th / 3,062 participants (top ~2.8%), final score 68.1/100.

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

## Known, disclosed limitations

- One safety-critical overestimate (`request_04`, +2.2M in local currency) was investigated exhaustively — ruled out missing categories, recurrence detection, estimator choice, trend, and horizon-boundary effects — and left unresolved rather than special-cased for one request.
- EUR-currency requests sit at a 12.9% overestimate rate after calibration, above the 10% target; the small sample (n=62) gives EUR's own calibrated value a wide confidence interval, so pushing the correction further risked overfitting to noise.
- An independent 30-request audit (fresh subagent, no shared context, sampled from the unlabeled 250-request evaluation set) found a recurring weakness in interpreting salary/income-change messages. Diagnosed but not fixed — any correction based on unlabeled evaluation requests would be holdout leakage with no way to verify it actually helps.
