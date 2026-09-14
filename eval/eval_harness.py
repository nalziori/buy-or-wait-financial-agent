"""
Evaluation harness for Buy or Wait? (HackerRank Orchestrate)

Purpose:
- Score the agent's predictions (dataset/output.csv-shaped) against a golden set
  (e.g. dataset/sample_requests.csv, which already has completed output columns,
  for a local self-check -- NOT the hidden eval set).
- The organizer scores 6 separate axes with unpublished weights, so this harness
  reports each axis independently instead of collapsing them into one accuracy
  number -- optimizing a single blended score here would be misleading.
- Includes format/sanity checks that catch degenerate or invalid strategies
  before they ever reach the organizer's grader.

Usage:
    python eval_harness.py --pred dataset/output.csv --gold dataset/sample_requests.csv
    python eval_harness.py --pred dataset/output.csv --gold dataset/sample_requests.csv --sample 5
    python eval_harness.py --pred dataset/output.csv --gold dataset/sample_requests.csv --show-failures
"""

import argparse
import csv
import random
import re
import statistics
import sys
from collections import Counter

ID_COL = "request_id"
CATEGORICAL_COLS = ["affordability_status", "recommended_payment_method"]
EXACT_MATCH_COLS = ["payment_plan", "earliest_date_for_full_payment", "spending_changes_needed"]
NUMERIC_COL = "amount_safe_to_pay"
NUMERIC_TOLERANCE = 0.01  # allow float rounding noise, not a scoring loophole

REQUIRED_COLS = [
    ID_COL,
    NUMERIC_COL,
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]

ALLOWED_STATUS = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
ALLOWED_METHOD = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}

DATE_RE = r"\d{4}-\d{2}-\d{2}"
PLAN_RE = re.compile(rf"^none$|^{DATE_RE}:-?\d+(\.\d+)?(\|{DATE_RE}:-?\d+(\.\d+)?)*$")
DATE_ONLY_RE = re.compile(rf"^{DATE_RE}$")


def load_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_plan(plan: str) -> list[tuple[str, float]] | None:
    """Parse 'YYYY-MM-DD:amount|...' into [(date, amount), ...], or None if malformed."""
    if not PLAN_RE.match(plan or ""):
        return None
    if plan == "none":
        return []
    parts = []
    for chunk in plan.split("|"):
        date, amount = chunk.split(":")
        parts.append((date, float(amount)))
    return parts


def sanity_check(preds: list[dict]) -> None:
    """Flag degenerate strategies and structurally invalid rows before scoring."""
    if not preds:
        print("[warning] Predictions file is empty.", file=sys.stderr)
        return

    missing_cols = [c for c in REQUIRED_COLS if c not in preds[0]]
    if missing_cols:
        print(f"[warning] Predictions file is missing required column(s): {missing_cols}", file=sys.stderr)

    ids = [row.get(ID_COL, "") for row in preds]
    dup_ids = [rid for rid, count in Counter(ids).items() if count > 1]
    if dup_ids:
        print(f"[warning] {len(dup_ids)} duplicate request_id(s), scoring will be skewed: {dup_ids[:5]}...", file=sys.stderr)

    total = len(preds)
    for col, allowed in (
        ("affordability_status", ALLOWED_STATUS),
        ("recommended_payment_method", ALLOWED_METHOD),
    ):
        counts = Counter(row.get(col, "") for row in preds)
        for label, count in counts.items():
            if label not in allowed:
                print(f"[warning] '{col}' contains disallowed value '{label}' ({count} row(s)).", file=sys.stderr)
            ratio = count / total
            if ratio > 0.9:
                print(
                    f"[warning] '{col}'='{label}' makes up {ratio:.0%} of predictions. "
                    f"Check the system isn't collapsing onto a single strategy.",
                    file=sys.stderr,
                )

    bad_amount = 0
    bad_plan_format = 0
    bad_plan_sum = 0
    bad_date = 0
    for row in preds:
        try:
            safe = float(row[NUMERIC_COL])
            requested = float(row.get("requested_amount", safe))  # only present if pred file carries it
            if not (0 <= safe <= requested + NUMERIC_TOLERANCE):
                bad_amount += 1
        except (ValueError, KeyError):
            pass

        plan = row.get("payment_plan", "")
        parsed = parse_plan(plan)
        if parsed is None:
            bad_plan_format += 1
        elif parsed:
            total_plan = sum(amt for _, amt in parsed)
            requested = row.get("requested_amount")
            if requested not in (None, ""):
                try:
                    if abs(total_plan - float(requested)) > NUMERIC_TOLERANCE:
                        bad_plan_sum += 1
                except ValueError:
                    pass

        earliest = row.get("earliest_date_for_full_payment", "")
        if earliest and not DATE_ONLY_RE.match(earliest):
            bad_date += 1

    if bad_amount:
        print(f"[warning] {bad_amount} row(s) have amount_safe_to_pay outside [0, requested_amount].", file=sys.stderr)
    if bad_plan_format:
        print(f"[warning] {bad_plan_format} row(s) have a malformed payment_plan (expected 'YYYY-MM-DD:amount|...' or 'none').", file=sys.stderr)
    if bad_plan_sum:
        print(f"[warning] {bad_plan_sum} row(s) have a payment_plan that doesn't sum to requested_amount.", file=sys.stderr)
    if bad_date:
        print(f"[warning] {bad_date} row(s) have a malformed earliest_date_for_full_payment (expected 'YYYY-MM-DD' or empty).", file=sys.stderr)


def score(preds: list[dict], golds: list[dict]) -> dict:
    """Match by request_id and report per-axis correctness (no single blended metric)."""
    gold_map = {row[ID_COL]: row for row in golds}
    pred_map = {row[ID_COL]: row for row in preds}

    missing = set(gold_map) - set(pred_map)
    if missing:
        print(f"[warning] {len(missing)} item(s) missing from predictions: {list(missing)[:5]}...")

    n = len(gold_map)
    axis_correct = {col: 0 for col in CATEGORICAL_COLS + EXACT_MATCH_COLS}
    confusion = {col: Counter() for col in CATEGORICAL_COLS}
    numeric_errors = []  # pred - gold, for rows present in both
    plan_partial = Counter()  # debug-only: dates_only / amounts_only / both / neither
    failing_ids = []  # any request with >=1 axis mismatch (excluding numeric tolerance misses)

    for _id, gold_row in gold_map.items():
        pred_row = pred_map.get(_id)
        if pred_row is None:
            continue

        row_failed = False
        for col in CATEGORICAL_COLS + EXACT_MATCH_COLS:
            gold_val = gold_row.get(col, "").strip()
            pred_val = pred_row.get(col, "").strip()
            if pred_val == gold_val:
                axis_correct[col] += 1
            else:
                row_failed = True
            if col in CATEGORICAL_COLS:
                confusion[col][(gold_val, pred_val)] += 1

        gold_plan = parse_plan(gold_row.get("payment_plan", ""))
        pred_plan = parse_plan(pred_row.get("payment_plan", ""))
        if gold_plan is not None and pred_plan is not None:
            gold_dates = [d for d, _ in gold_plan]
            pred_dates = [d for d, _ in pred_plan]
            gold_amts = [a for _, a in gold_plan]
            pred_amts = [a for _, a in pred_plan]
            dates_match = gold_dates == pred_dates
            amounts_match = gold_amts == pred_amts
            if dates_match and amounts_match:
                plan_partial["both_match"] += 1
            elif dates_match:
                plan_partial["dates_only"] += 1
            elif amounts_match:
                plan_partial["amounts_only"] += 1
            else:
                plan_partial["neither"] += 1

        try:
            gold_amt = float(gold_row[NUMERIC_COL])
            pred_amt = float(pred_row[NUMERIC_COL])
            numeric_errors.append(pred_amt - gold_amt)
            if abs(gold_amt - pred_amt) > NUMERIC_TOLERANCE:
                row_failed = True
        except (ValueError, KeyError):
            pass

        if row_failed:
            failing_ids.append(_id)

    numeric_stats = None
    if numeric_errors:
        hits = sum(1 for e in numeric_errors if abs(e) <= NUMERIC_TOLERANCE)
        numeric_stats = {
            "accuracy": hits / len(numeric_errors),
            "mean_error": statistics.mean(numeric_errors),
            "stdev_error": statistics.pstdev(numeric_errors) if len(numeric_errors) > 1 else 0.0,
            "max_abs_error": max(abs(e) for e in numeric_errors),
        }

    return {
        "n_gold": n,
        "n_missing": len(missing),
        "axis_accuracy": {col: (axis_correct[col] / n if n else 0.0) for col in axis_correct},
        "confusion": confusion,
        "numeric_stats": numeric_stats,
        "plan_partial": plan_partial,
        "failing_ids": failing_ids,
    }


def print_confusion(confusion: dict) -> None:
    print("\nConfusion (gold -> pred, mismatches only):")
    for col, counts in confusion.items():
        mismatches = {k: v for k, v in counts.items() if k[0] != k[1]}
        if not mismatches:
            print(f"  {col}: no mismatches")
            continue
        print(f"  {col}:")
        for (gold_val, pred_val), count in sorted(mismatches.items(), key=lambda x: -x[1]):
            print(f"    {gold_val or '<empty>'} -> {pred_val or '<empty>'}: {count}")


def print_sample(preds: list[dict], golds: list[dict], n: int, only_failing: set | None = None) -> None:
    pred_map = {row[ID_COL]: row for row in preds}
    pool = [row for row in golds if only_failing is None or row[ID_COL] in only_failing]
    if not pool:
        print("\n[sample] No matching rows to sample.")
        return
    sample = random.sample(pool, min(n, len(pool)))
    print(f"\n[sample] {len(sample)} row(s){' (failures only)' if only_failing is not None else ''}:")
    for gold_row in sample:
        pred_row = pred_map.get(gold_row[ID_COL], {})
        print(f"\n  request_id: {gold_row[ID_COL]}")
        print(f"    gold: {gold_row.get('decision_explanation', '')}")
        print(f"    pred: {pred_row.get('decision_explanation', '<missing>')}")


def export_failures(preds: list[dict], golds: list[dict], failing_ids: list[str], path: str) -> None:
    """Write failing rows (gold + pred side by side, with the mismatching axes named) to a CSV.

    Not training data for fine-tuning -- there's neither the time nor the row count for that in
    a same-day hackathon. Use this as few-shot examples in the prompt or a regression checklist.
    """
    pred_map = {row[ID_COL]: row for row in preds}
    axes = CATEGORICAL_COLS + EXACT_MATCH_COLS + [NUMERIC_COL]
    fieldnames = [ID_COL, "mismatched_axes"] + [f"gold_{c}" for c in axes] + [f"pred_{c}" for c in axes]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for gold_row in golds:
            _id = gold_row[ID_COL]
            if _id not in failing_ids:
                continue
            pred_row = pred_map.get(_id, {})
            mismatched = []
            for c in axes:
                gold_val, pred_val = gold_row.get(c, "").strip(), pred_row.get(c, "").strip()
                if c == NUMERIC_COL:
                    try:
                        if abs(float(gold_val) - float(pred_val)) > NUMERIC_TOLERANCE:
                            mismatched.append(c)
                    except ValueError:
                        mismatched.append(c)
                elif gold_val != pred_val:
                    mismatched.append(c)
            out_row = {ID_COL: _id, "mismatched_axes": "|".join(mismatched)}
            for c in axes:
                out_row[f"gold_{c}"] = gold_row.get(c, "")
                out_row[f"pred_{c}"] = pred_row.get(c, "")
            writer.writerow(out_row)

    print(f"\n[export] Wrote {len(failing_ids)} failing row(s) to {path}")


def eval_loop_reminder() -> None:
    """Nudge to close the eval loop (build -> run -> inspect failures -> fix -> rerun)."""
    print(
        "\n[reminder] decision_explanation quality isn't auto-scored here -- use --sample or "
        "--show-failures to read rows by hand each iteration. Also: sample_requests.csv is a "
        "style reference, not the hidden golden set, so a perfect local score doesn't guarantee "
        "the real one. Log each iteration in the 'Eval Loop Log' section of CLAUDE.md.",
        file=sys.stderr,
    )


def main():
    parser = argparse.ArgumentParser(description="Score Buy or Wait? predictions against a golden/sample set")
    parser.add_argument("--pred", required=True, help="Path to the agent's predictions CSV")
    parser.add_argument("--gold", required=True, help="Path to the golden/sample CSV (must include the output columns)")
    parser.add_argument("--sample", type=int, default=0, help="Print N random gold/pred decision_explanation pairs")
    parser.add_argument("--show-failures", action="store_true", help="Restrict --sample to rows with at least one axis mismatch")
    parser.add_argument("--export-failures", metavar="PATH", help="Write failing rows (gold+pred, mismatched axes named) to a CSV for few-shot/regression use")
    args = parser.parse_args()

    preds = load_csv(args.pred)
    golds = load_csv(args.gold)

    sanity_check(preds)
    result = score(preds, golds)

    print(f"\nScored against {result['n_gold']} item(s); missing predictions: {result['n_missing']}")
    print("\nPer-axis exact-match accuracy:")
    for col, acc in result["axis_accuracy"].items():
        print(f"  {col}: {acc:.2%}")

    if result["numeric_stats"]:
        ns = result["numeric_stats"]
        print(f"  {NUMERIC_COL} (within {NUMERIC_TOLERANCE}): {ns['accuracy']:.2%}")
        print(f"    error (pred - gold): mean={ns['mean_error']:.2f}, stdev={ns['stdev_error']:.2f}, max_abs={ns['max_abs_error']:.2f}")

    if result["plan_partial"]:
        print("\npayment_plan partial match (debug only, not part of official scoring):")
        for label, count in result["plan_partial"].items():
            print(f"  {label}: {count}")

    print_confusion(result["confusion"])

    if args.sample:
        only_failing = set(result["failing_ids"]) if args.show_failures else None
        print_sample(preds, golds, args.sample, only_failing=only_failing)

    if args.export_failures:
        export_failures(preds, golds, result["failing_ids"], args.export_failures)

    eval_loop_reminder()


if __name__ == "__main__":
    main()
