"""Test-only run (not a production change): score the 25 public samples with the per-currency
shrunk safety buffer from eval/lambda_calibration.py's shrinkage step (k=60), vs the flat global
lambda=0.0192 baseline. Config.safety_buffer_frac stays 0.0 in code/forecast.py; this only builds a
local Config override for the comparison run.

Usage:
    python eval/test_currency_shrink_25.py
"""
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

GLOBAL_LAMBDA = 0.0192
SHRUNK_BY_CURRENCY = {"EUR": 0.0231, "IDR": 0.0170, "INR": 0.0157, "USD": 0.0158, "ZAR": 0.0162}


def score(ds, facts, cfg):
    diffs, over, by_cur = [], 0, {}
    for s in ds.samples:
        rd = date.fromisoformat(s["request_date"])
        f = build_forecast(ds, s["user_id"], rd, facts.get(s["user_id"], []), cfg=cfg)
        row = row_for(decide(ds, s, f))
        d = float(row["amount_safe_to_pay"]) - float(s["amount_safe_to_pay"])
        diffs.append(abs(d))
        over += d > 0.01
        cur = ds.profiles[s["user_id"]]["home_currency"]
        by_cur.setdefault(cur, [0, 0])
        by_cur[cur][0] += 1
        by_cur[cur][1] += d > 0.01
    return sum(diffs) / len(diffs), over, by_cur


def main():
    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    resolve_image_amounts(ds, llm)
    facts = extract_message_facts(ds, llm)

    cfg_global = replace(Config(), safety_buffer_frac=GLOBAL_LAMBDA)
    cfg_shrunk = replace(Config(), safety_buffer_frac=GLOBAL_LAMBDA, safety_buffer_by_currency=SHRUNK_BY_CURRENCY)

    mae_g, over_g, by_cur_g = score(ds, facts, cfg_global)
    mae_s, over_s, by_cur_s = score(ds, facts, cfg_shrunk)
    n = len(ds.samples)

    print(f"flat global lambda=0.0192   MAE={mae_g:,.1f}  safety_over_rate={over_g}/{n}={over_g/n:.0%}")
    print(f"per-currency shrunk map     MAE={mae_s:,.1f}  safety_over_rate={over_s}/{n}={over_s/n:.0%}")

    print("\nper-currency breakdown (reference only, n=1-8, not used as evidence):")
    for cur in sorted(set(by_cur_g) | set(by_cur_s)):
        ng, og = by_cur_g.get(cur, (0, 0))
        ns, os_ = by_cur_s.get(cur, (0, 0))
        print(f"  {cur:<5} n={ng}  over(global)={og}/{ng}  over(shrunk)={os_}/{ns}")


if __name__ == "__main__":
    main()
