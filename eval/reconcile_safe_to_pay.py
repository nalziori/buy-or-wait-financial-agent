"""Phase 1/2 reconciliation for amount_safe_to_pay: per-request formula trace + bottleneck window.

Uses only cached Gemini facts already on disk. Makes no new API calls, no production changes.
Ground truth is used only to compute error columns, never to build intermediate forecast values.

Usage:
    python eval/reconcile_safe_to_pay.py
"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from data import Dataset  # noqa: E402
from evidence import extract_message_facts, resolve_image_amounts  # noqa: E402
from forecast import build_forecast  # noqa: E402
from llm import LLM  # noqa: E402
from main import row_for  # noqa: E402
from planner import decide  # noqa: E402

WINDOW = 7


def main():
    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    resolve_image_amounts(ds, llm)
    facts = extract_message_facts(ds, llm)

    print(f"{'request_id':<12}{'pred_safe':>14}{'gold_safe':>14}{'signed_err':>14}{'abs_err':>12}"
          f"{'bottleneck':>13}{'margin@btlnk':>14}{'balance':>12}{'min_bal':>10}")
    for s in ds.samples:
        rid, uid = s["request_id"], s["user_id"]
        rd = date.fromisoformat(s["request_date"])
        f = build_forecast(ds, uid, rd, facts.get(uid, []))
        decision = decide(ds, s, f)
        row = row_for(decision)

        lows = f.lows()
        trough = lows.index(min(lows))
        pred = float(row["amount_safe_to_pay"])
        gold = float(s["amount_safe_to_pay"])
        signed = pred - gold

        print(f"{rid:<12}{pred:>14,.2f}{gold:>14,.2f}{signed:>+14,.2f}{abs(signed):>12,.2f}"
              f"{str(f.start + timedelta(days=trough)):>13}{lows[trough]-f.min_balance:>14,.2f}"
              f"{f.balance:>12,.2f}{f.min_balance:>10,.2f}")

        # Local window around the bottleneck: which items actually move the balance there.
        lo, hi = max(0, trough - WINDOW), min(f.days - 1, trough + WINDOW)
        window_start, window_end = f.start + timedelta(days=lo), f.start + timedelta(days=hi)
        local = defaultdict(lambda: [0, 0.0])
        for d, amt, label, eid in f.items:
            if window_start <= d <= window_end:
                local[label][0] += 1
                local[label][1] += amt
        top3 = sorted(local.items(), key=lambda kv: kv[1][1])[:3]
        print(f"    window [{window_start}..{window_end}] top contributors (n, signed total):")
        for label, (cnt, total) in top3:
            print(f"      {label:<28} n={cnt:<3} total={total:>12,.2f}")

        # Global contributors up to the bottleneck (for distinguishing local vs accumulated-drift error).
        global_by_label = defaultdict(lambda: [0, 0.0])
        for d, amt, label, eid in f.items:
            if (d - f.start).days <= trough:
                global_by_label[label][0] += 1
                global_by_label[label][1] += amt
        top3_global = sorted(global_by_label.items(), key=lambda kv: kv[1][1])[:3]
        print(f"    cumulative-to-bottleneck top contributors:")
        for label, (cnt, total) in top3_global:
            print(f"      {label:<28} n={cnt:<3} total={total:>12,.2f}")


if __name__ == "__main__":
    main()
