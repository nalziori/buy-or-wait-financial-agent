"""Synthetic formula audit for amount_safe_to_pay, independent of the 25 sample outputs.

Verifies the safe-on-day-0 formula (bottleneck min-balance walk, clip to [0, requested]) against
hand-computed expected values for small constructed scenarios.

Usage:
    python eval/test_safe_to_pay_formula.py
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from forecast import Forecast  # noqa: E402

START = date(2026, 1, 1)


def fc(balance, min_balance, items, days=90):
    return Forecast(start=START, days=days, balance=balance, min_balance=min_balance, items=items, series=[])


def test_single_future_debit():
    # balance=1000, min=100, one 500 debit on day 10 -> min balance over horizon is 500, safe = 500-100 = 400.
    f = fc(1000, 100, [(START + timedelta(days=10), -500, "x", "e1")])
    assert f.safe_on(0) == 400.0, f.safe_on(0)


def test_cap_at_zero_when_min_already_breached_by_history():
    # a debit deep enough that the margin goes negative -> capped at 0, never negative.
    f = fc(1000, 100, [(START + timedelta(days=5), -2000, "x", "e1")])
    assert f.safe_on(0) == 0.0, f.safe_on(0)


def test_day_zero_event_counts_in_day_zero_balance():
    # an item dated exactly on request_date (offset 0) must reduce the safe amount, not be excluded as "future".
    f = fc(1000, 100, [(START, -400, "x", "e1")])
    assert f.safe_on(0) == 500.0, f.safe_on(0)  # 1000-400-100


def test_income_after_bottleneck_does_not_rescue_the_minimum():
    # a 500 debit on day 10, then a 2000 credit on day 20 -> the pre-day-20 trough is still the binding constraint.
    f = fc(1000, 100, [(START + timedelta(days=10), -500, "x", "e1"), (START + timedelta(days=20), 2000, "y", "e2")])
    assert f.safe_on(0) == 400.0, f.safe_on(0)


def test_horizon_is_90_days_inclusive_of_start():
    f = fc(1000, 100, [])
    assert f.days == 90
    assert f.end == START + timedelta(days=89)  # 90 calendar days total, day 0 = request_date


def test_earliest_full_payment_today_when_already_safe():
    f = fc(1000, 100, [])
    assert f.earliest_full(400) == START


def test_earliest_full_payment_never_exceeds_the_true_horizon_max():
    # balance never exceeds 500 anywhere in the horizon (1000 - 500 debit, no further income) -> 700 is
    # never safe, regardless of how far out you look. Must return None, not silently pick some later date.
    f = fc(1000, 100, [(START + timedelta(days=10), -500, "x", "e1")])
    assert f.earliest_full(700) is None


def test_earliest_full_payment_waits_for_a_later_credit_to_clear_the_trough():
    # 500 debit on day 10, then a 1000 credit on day 20 raises the post-day-20 floor to 1500 -> 700 becomes
    # safe only once that credit has settled, not before.
    f = fc(1000, 100, [(START + timedelta(days=10), -500, "x", "e1"), (START + timedelta(days=20), 1000, "y", "e2")])
    assert f.earliest_full(700) == START + timedelta(days=20)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all formula checks passed")
