"""Full standard metric set (same shape as eval/compare_samples.py) for the 25 public samples under
the per-currency shrunk safety buffer -- test only, Config.safety_buffer_frac production default
stays 0.0 in code/forecast.py.

Usage:
    python eval/test_currency_shrink_full_metrics.py
"""
import statistics
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from data import Dataset  # noqa: E402
from evidence import extract_message_facts, resolve_image_amounts  # noqa: E402
from forecast import Config, build_forecast  # noqa: E402
from llm import LLM  # noqa: E402
from main import row_for  # noqa: E402
from planner import decide  # noqa: E402

CATEGORICAL = ["affordability_status", "recommended_payment_method"]
EXACT = ["payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]
TOL = 0.01

GLOBAL_LAMBDA = 0.0192
SHRUNK_BY_CURRENCY = {"EUR": 0.0231, "IDR": 0.0170, "INR": 0.0157, "USD": 0.0158, "ZAR": 0.0162}


def main():
    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    resolve_image_amounts(ds, llm)
    facts = extract_message_facts(ds, llm)
    cfg = replace(Config(), safety_buffer_frac=GLOBAL_LAMBDA, safety_buffer_by_currency=SHRUNK_BY_CURRENCY)

    n = len(ds.samples)
    errors, over, axis_correct, exact_all = [], 0, {c: 0 for c in CATEGORICAL + EXACT}, 0
    for s in ds.samples:
        rd = date.fromisoformat(s["request_date"])
        f = build_forecast(ds, s["user_id"], rd, facts.get(s["user_id"], []), cfg=cfg)
        row = row_for(decide(ds, s, f))
        diff = float(row["amount_safe_to_pay"]) - float(s["amount_safe_to_pay"])
        errors.append(diff)
        over += diff > TOL
        wrong = [c for c in CATEGORICAL + EXACT if row[c].strip() != s[c].strip()]
        for c in CATEGORICAL + EXACT:
            if c not in wrong:
                axis_correct[c] += 1
        exact_all += not wrong and abs(diff) <= TOL

    abs_errors = [abs(e) for e in errors]
    exact_amount = sum(1 for e in abs_errors if e <= TOL)
    print("=== per-currency shrunk buffer: amount_safe_to_pay ===")
    print(f"exact match (+/-{TOL}): {exact_amount}/{n} ({exact_amount/n:.0%})")
    print(f"MAE: {statistics.mean(abs_errors):,.2f}")
    print(f"median absolute error: {statistics.median(abs_errors):,.2f}")
    print(f"SAFETY-CRITICAL overestimation rate: {over}/{n} ({over/n:.0%})")
    print()
    print("=== per-axis accuracy ===")
    for c in CATEGORICAL + EXACT:
        print(f"{c}: {axis_correct[c]}/{n} ({axis_correct[c]/n:.0%})")
    print()
    print(f"=== overall exact-match (all 6 axes) === {exact_all}/{n} ({exact_all/n:.0%})")


if __name__ == "__main__":
    main()
