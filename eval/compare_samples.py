"""Field-by-field comparison of eval/sample_predictions.csv against dataset/sample_requests.csv.

Usage:
    python eval/compare_samples.py
"""
import csv
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORICAL = ["affordability_status", "recommended_payment_method"]
EXACT = ["payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]
TOL = 0.01


def load(path):
    return {r["request_id"]: r for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}


def main():
    gold = load(ROOT / "dataset" / "sample_requests.csv")
    pred = load(ROOT / "eval" / "sample_predictions.csv")
    ids = sorted(gold, key=lambda r: int(r.split("_")[1]))
    n = len(ids)

    errors, over, under, exact_amount = [], 0, 0, 0
    axis_correct = {c: 0 for c in CATEGORICAL + EXACT}
    exact_all = 0

    print(f"{'id':<12}{'gold_safe':>14}{'pred_safe':>14}{'diff':>12}  axes wrong")
    for rid in ids:
        g, p = gold[rid], pred[rid]
        g_amt, p_amt = float(g["amount_safe_to_pay"]), float(p["amount_safe_to_pay"])
        diff = p_amt - g_amt
        errors.append(diff)
        if diff > 0:
            over += 1
        elif diff < 0:
            under += 1
        if abs(diff) <= TOL:
            exact_amount += 1

        wrong = [c for c in CATEGORICAL + EXACT if p[c].strip() != g[c].strip()]
        for c in CATEGORICAL + EXACT:
            if c not in wrong:
                axis_correct[c] += 1
        row_exact = not wrong and abs(diff) <= TOL
        exact_all += row_exact
        flag = " ".join(wrong) if wrong or abs(diff) > TOL else ""
        print(f"{rid:<12}{g_amt:>14,.2f}{p_amt:>14,.2f}{diff:>+12,.2f}  {flag}")

    abs_errors = [abs(e) for e in errors]
    print()
    print("=== amount_safe_to_pay ===")
    print(f"exact match (±{TOL}): {exact_amount}/{n} ({exact_amount/n:.0%})")
    print(f"MAE: {statistics.mean(abs_errors):,.2f}")
    print(f"median absolute error: {statistics.median(abs_errors):,.2f}")
    print(f"max error: {max(abs_errors):,.2f}  (request {ids[abs_errors.index(max(abs_errors))]})")
    print(f"overestimated (pred > gold): {over}/{n}")
    print(f"underestimated (pred < gold): {under}/{n}")
    print(f"exact: {n - over - under}/{n}")
    print(f"SAFETY-CRITICAL overestimation rate (pred > gold, i.e. recommends more than truly safe): {over}/{n} ({over/n:.0%})")

    print()
    print("=== per-axis accuracy ===")
    for c in CATEGORICAL + EXACT:
        print(f"{c}: {axis_correct[c]}/{n} ({axis_correct[c]/n:.0%})")

    print()
    print(f"=== overall exact-match (all 6 axes incl. amount_safe_to_pay ±{TOL}) ===")
    print(f"{exact_all}/{n} ({exact_all/n:.0%})")


if __name__ == "__main__":
    main()
