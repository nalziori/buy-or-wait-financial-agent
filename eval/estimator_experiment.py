"""Compare recurring-expense estimators on the 25 samples through the FULL pipeline (not just the forecast).

Runs decide() under each Config.amount_estimator, computes the same 8 metrics as compare_samples.py plus
signed error by expense category. Uses cached Gemini facts already on disk (gemini-3.5-flash); makes no new
API calls. No estimator is tuned to any individual request_id.

Usage:
    python eval/estimator_experiment.py
"""
import statistics
import sys
from collections import Counter, defaultdict
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

VARIANTS = {
    "current/mean": Config(),
    "median": replace(Config(), amount_estimator="median"),
    "last": replace(Config(), amount_estimator="last"),
    "max": replace(Config(), amount_estimator="max"),
    "recent_window_mean (last3)": replace(Config(), amount_estimator="mean_last3"),
    "recent_window_median (last3)": replace(Config(), amount_estimator="median_last3"),
    "linear_trend": replace(Config(), amount_estimator="linear_trend"),
    "damped_trend": replace(Config(), amount_estimator="damped_trend"),
}


def run_variant(ds, facts, cfg):
    rows = {}
    category_error = defaultdict(list)  # category -> list of (pred_debit_total - implied) not derivable directly;
    for s in ds.samples:
        rd = date.fromisoformat(s["request_date"])
        f = build_forecast(ds, s["user_id"], rd, facts.get(s["user_id"], []), cfg=cfg)
        decision = decide(ds, s, f)
        rows[s["request_id"]] = row_for(decision)
        # signed contribution per category up to the trough day, for later aggregation
        lows = f.lows()
        trough = lows.index(min(lows))
        for d, amt, label, eid in f.items:
            if label.startswith("series:") and (d - f.start).days <= trough:
                category_error[label.split(":", 1)[1]].append(amt)
    return rows, category_error


def score(gold, pred, ids=None):
    ids = ids or list(gold)
    diffs = [float(pred[r]["amount_safe_to_pay"]) - float(gold[r]["amount_safe_to_pay"]) for r in ids]
    abs_d = [abs(d) for d in diffs]
    axis = {c: sum(1 for r in ids if pred[r][c].strip() == gold[r][c].strip()) for c in CATEGORICAL + EXACT}
    exact_amt = sum(1 for d in abs_d if d <= TOL)
    exact_all = sum(
        1
        for r in ids
        if abs(float(pred[r]["amount_safe_to_pay"]) - float(gold[r]["amount_safe_to_pay"])) <= TOL
        and all(pred[r][c].strip() == gold[r][c].strip() for c in CATEGORICAL + EXACT)
    )
    return {
        "n": len(ids),
        "exact_amount": exact_amt,
        "mae": statistics.mean(abs_d),
        "median_ae": statistics.median(abs_d),
        "over": sum(1 for d in diffs if d > TOL),
        "under": sum(1 for d in diffs if d < -TOL),
        "axis": axis,
        "exact_all": exact_all,
    }


def main():
    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    resolve_image_amounts(ds, llm)
    facts = extract_message_facts(ds, llm)
    gold = {r["request_id"]: r for r in ds.samples}

    print(f"{'variant':<30}{'safe_exact':>11}{'MAE':>14}{'medAE':>10}{'over':>6}{'under':>7}"
          f"{'safety_over%':>13}{'status%':>9}{'method%':>9}{'plan%':>8}{'earliest%':>11}{'spend%':>8}{'all6%':>8}")
    results = {}
    for name, cfg in VARIANTS.items():
        pred, cat_err = run_variant(ds, facts, cfg)
        r = score(gold, pred)
        n = r["n"]
        results[name] = (r, cat_err, pred)
        print(
            f"{name:<30}{r['exact_amount']:>4}/{n:<6}{r['mae']:>14,.1f}{r['median_ae']:>10,.1f}"
            f"{r['over']:>6}{r['under']:>7}{r['over']/n:>12.0%}"
            f"{r['axis']['affordability_status']/n:>9.0%}{r['axis']['recommended_payment_method']/n:>9.0%}"
            f"{r['axis']['payment_plan']/n:>8.0%}{r['axis']['earliest_date_for_full_payment']/n:>11.0%}"
            f"{r['axis']['spending_changes_needed']/n:>8.0%}{r['exact_all']/n:>7.0%}"
        )

    # Rotating 20-dev/5-holdout split, purely as an anti-overfitting sanity check (not a rigorous held-out
    # estimate with only 25 points). Holdout membership is fixed by request_id order, decided before looking
    # at any per-round results, and never adjusted afterward.
    ids = sorted(gold, key=lambda r: int(r.split("_")[1]))
    rounds = [ids[i::5] for i in range(5)]  # 5 disjoint 5-id groups; each round holds one out
    print("\nRotating holdout (5 rounds of 5-held-out / 20-dev, holdout membership fixed in advance):")
    print(f"{'variant':<30}{'round':<8}{'dev_MAE':>12}{'holdout_MAE':>13}{'dev_safety_over%':>18}{'holdout_safety_over%':>21}")
    for name, (_, _, pred) in results.items():
        for i, holdout in enumerate(rounds):
            dev = [x for x in ids if x not in holdout]
            dr, hr = score(gold, pred, dev), score(gold, pred, holdout)
            print(
                f"{name:<30}{i:<8}{dr['mae']:>12,.0f}{hr['mae']:>13,.0f}"
                f"{dr['over']/dr['n']:>18.0%}{hr['over']/hr['n']:>21.0%}"
            )

    print("\nSigned mean per-occurrence amount by category (up to each request's trough day), current/mean vs recent_window_mean:")
    base_cat = results["current/mean"][1]
    alt_cat = results["recent_window_mean (last3)"][1]
    all_cats = sorted(set(base_cat) | set(alt_cat))
    print(f"{'category':<20}{'n_occ(base)':>12}{'mean(base)':>14}{'mean(recent3)':>16}{'delta':>12}")
    for cat in all_cats:
        b = base_cat.get(cat, [])
        a = alt_cat.get(cat, [])
        if not b or not a:
            continue
        mb, ma = statistics.mean(b), statistics.mean(a)
        print(f"{cat:<20}{len(b):>12}{mb:>14,.2f}{ma:>16,.2f}{ma-mb:>+12,.2f}")


if __name__ == "__main__":
    main()
