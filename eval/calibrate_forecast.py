"""Score forecast knob combinations against sample_requests.csv (amount_safe_to_pay + earliest date).

Usage:
    python eval/calibrate_forecast.py                 # variant table
    python eval/calibrate_forecast.py request_06      # item-level trace for one sample (default config)
"""
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from data import Dataset  # noqa: E402
from forecast import Config, build_forecast  # noqa: E402


def run(ds, sample, cfg):
    f = build_forecast(ds, sample["user_id"], date.fromisoformat(sample["request_date"]), cfg=cfg)
    requested = float(sample["requested_amount"])
    return f, min(requested, f.safe_on(0)), f.earliest_full(requested)


def trace(ds, request_id):
    sample = next(s for s in ds.samples if s["request_id"] == request_id)
    f, safe, earliest = run(ds, sample, Config())
    lows = f.lows()
    trough = min(range(f.days), key=lambda i: lows[i])
    print(f"{request_id} balance={f.balance} min={f.min_balance} trough_day={f.start.toordinal() + trough - f.start.toordinal()} "
          f"expected_safe={sample['amount_safe_to_pay']} got={safe:.2f} expected_earliest={sample['earliest_date_for_full_payment']} got={earliest}")
    for d, amount, label, eid in f.items:
        if (d - f.start).days <= trough:
            print(f"  {d} {amount:>14.2f} {label} {eid}")


def main():
    ds = Dataset()
    if len(sys.argv) > 1:
        trace(ds, sys.argv[1])
        return
    base = Config()
    variants = {
        "default(mean)": base,
        "max": replace(base, amount_estimator="max"),
        "last": replace(base, amount_estimator="last"),
        "mean_last3": replace(base, amount_estimator="mean_last3"),
        "median": replace(base, amount_estimator="median"),
        "no_request_day": replace(base, project_on_request_day=False),
        "horizon91": replace(base, horizon_days=91),
    }
    for name, cfg in variants.items():
        within1 = within5 = dates = 0
        detail = []
        for s in ds.samples:
            _, safe, earliest = run(ds, s, cfg)
            expected = float(s["amount_safe_to_pay"])
            err = abs(safe - expected) / max(expected, 1)
            within1 += err <= 0.01
            within5 += err <= 0.05
            dates += (earliest.isoformat() if earliest else "") == s["earliest_date_for_full_payment"]
            detail.append(f"{s['request_id'][-2:]}:{(safe - expected) / max(expected, 1):+.0%}")
        n = len(ds.samples)
        print(f"{name:<16} safe±1%={within1}/{n} safe±5%={within5}/{n} earliest_exact={dates}/{n}")
        print("   ", " ".join(detail))


if __name__ == "__main__":
    main()
