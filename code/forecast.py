"""Deterministic 90-day balance forecast for one user as of a request date.

Recurring series come from fitting date grids (monthly-by-day or every-N-days) to settled history.
Pending/scheduled debits, scheduled salary, and typed message facts are layered on top.
"""
import calendar
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from statistics import mean, median, pstdev

SALARY_MATCH_DAYS = 7
DEBIT_TYPES = {"expense", "subscription", "debt_payment", "investment_purchase"}


@dataclass(frozen=True)
class Config:
    horizon_days: int = 90
    amount_estimator: str = "mean"  # mean | max | last | mean_last3
    min_nday_hits: int = 3
    min_monthly_hits: int = 2
    project_on_request_day: bool = True
    # Conformal-risk-control calibration (eval/lambda_calibration.py, 275-user historical backtest, eps=0.10):
    # global lambda=0.0192 is the fallback; per-currency values are a k=60 shrinkage blend towards it.
    # Frozen 2026-09-13 -- see log.txt for the calibration/verification trail.
    safety_buffer_frac: float = 0.0192  # fraction of balance held back on top of min_balance, for any currency not listed below
    safety_buffer_by_currency: dict = field(
        default_factory=lambda: {"EUR": 0.0231, "IDR": 0.0170, "INR": 0.0157, "USD": 0.0158, "ZAR": 0.0162}
    )


def add_months(d, n):
    total = d.month - 1 + n
    year, month = d.year + total // 12, total % 12 + 1
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1]))


def grid_point(anchor, period, k):
    return add_months(anchor, k) if period == "monthly" else anchor + timedelta(days=period * k)


def fit(events, anchor, period):
    """On-grid events (oldest first) and grid points missed between the first hit and the anchor."""
    by_date = defaultdict(list)
    for e in events:
        by_date[e["date"]].append(e)
    earliest = min(by_date)
    hits, misses, gap, k = [], 0, 0, 0
    while (point := grid_point(anchor, period, -k)) >= earliest:
        if by_date.get(point):
            hits.append(by_date[point][0])
            misses += gap
            gap = 0
        else:
            gap += 1
        k += 1
    return hits[::-1], misses


SHORT_PERIOD_PENALTY = 8.0  # per unit of raw-interval CV, scaled by how much shorter than the typical raw gap


MIN_GAPS_FOR_DISPERSION = 4  # a coefficient of variation from fewer raw gaps isn't statistically meaningful


def interval_dispersion(events):
    """(typical raw gap in days, coefficient of variation of raw gaps). CV=0 for a perfectly regular sequence
    or when there aren't enough gaps to judge irregularity at all (falls back to plain hit-count scoring)."""
    gaps = sorted((b["date"] - a["date"]).days for a, b in zip(events, events[1:]))
    if len(gaps) < MIN_GAPS_FOR_DISPERSION:
        return (mean(gaps) if gaps else 30.0), 0.0
    m = mean(gaps)
    return m, (pstdev(gaps) / m if m else 0.0)


def best_grid(events):
    """Score each candidate grid on net hits, adjusted for how well it's supported:

    - coverage: the fraction of this group's events the grid actually explains (a grid that only
      explains a minority is more likely a coincidental subset match than a real cadence).
    - short-period penalty: a short candidate period is only penalized when the RAW event timing is
      itself irregular (high coefficient of variation) AND the period is much shorter than the typical
      raw gap -- a perfectly regular short cadence (CV=0, e.g. a fixed 5-day charge) pays no penalty at
      all, so this never suppresses a genuine high-frequency recurrence, only a spurious one fitted to
      naturally bursty data.
    """
    intervals = {(b["date"] - a["date"]).days for a, b in zip(events, events[1:])}
    periods = ["monthly"] + sorted(p for p in intervals if p >= 5)
    avg_gap, cv = interval_dispersion(events)
    best = None
    for anchor in {e["date"] for e in events[-4:]}:
        for period in periods:
            hits, misses = fit(events, anchor, period)
            coverage = len(hits) / len(events)
            period_days = 30 if period == "monthly" else period
            shortness = max(0.0, avg_gap / period_days - 1)
            penalty = SHORT_PERIOD_PENALTY * cv * shortness
            score = (round(len(hits) - misses - penalty + coverage, 4), period == "monthly", anchor)
            if best is None or score > best[0]:
                best = (score, period, hits)
    return best[1], best[2]


def detect_series(events, cfg):
    groups = defaultdict(list)
    for e in events:
        if e["status"] != "settled" or e["amount_home"] is None:
            continue
        if (e["direction"] == "debit" and e["type"] in DEBIT_TYPES) or (e["direction"] == "credit" and e["category"] == "salary"):
            groups[(e["type"], e["category"], e["direction"])].append(e)
    series = []
    for key, group in groups.items():
        remaining = sorted(group, key=lambda e: e["date"])
        while len(remaining) >= 2:
            period, hits = best_grid(remaining)
            if len(hits) < (cfg.min_monthly_hits if period == "monthly" else cfg.min_nday_hits):
                break
            series.append({"key": key, "period": period, "events": hits})
            taken = {e["id"] for e in hits}
            remaining = [e for e in remaining if e["id"] not in taken]
    return series


def trend_slope(amounts):
    """Ordinary least-squares slope of amounts against their chronological index."""
    n = len(amounts)
    xs = range(n)
    mx, my = (n - 1) / 2, mean(amounts)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, amounts))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def estimate(amounts, how):
    if how == "max":
        return max(amounts)
    if how == "last":
        return amounts[-1]
    if how == "median":
        return median(amounts)
    if how == "mean_last3":
        return mean(amounts[-3:])
    if how == "median_last3":
        return median(amounts[-3:])
    if how == "linear_trend" and len(amounts) >= 3:
        return max(0.0, mean(amounts) + trend_slope(amounts) * (len(amounts) + 1) / 2)
    if how == "damped_trend" and len(amounts) >= 3:
        return max(0.0, amounts[-1] + 0.7 * trend_slope(amounts))
    return mean(amounts)


def stable_amount(amounts):
    """Most common of the last three amounts if it repeats; variable income (commission, gig pay) returns None."""
    amount, count = Counter(round(a, 2) for a in amounts[-3:]).most_common(1)[0]
    return amount if count >= 2 else None


def fact_amount(ds, fact, home, day):
    if fact["amount"] is None:
        return None
    currency = fact["currency"] if fact["currency"] in ds.currencies else home
    return fact["amount"] * ds.fx.rate(currency, home, day)


SALARY_CONFLICT_TOLERANCE = 0.10  # a fact must be within 10% of a stable settled series, or carry its own effective_date


def settled_salary_refs(series):
    """Stable (repeated, non-variable) settled amounts from every detected credit series -- the 'known good' baseline."""
    refs = []
    for s in series:
        if s["key"][0] == "income" and s["key"][2] == "credit":
            ref = stable_amount([h["amount_home"] for h in s["events"]])
            if ref is not None:
                refs.append(ref)
    return refs


def apply_facts(ds, salary, items, facts, home, request_date, end, series=(), notes=None):
    """Layer typed message facts over projected salary and expense items (newest message last wins).

    Conflict rule (spec order: explicit amendment > newer same-source record > settled over estimate/forecast >
    conservative when still ambiguous): a salary-amount fact with no effective_date is an undated claim, not a
    dated amendment. If it contradicts a stable, repeatedly-settled income series by more than the tolerance,
    settled history wins and the fact is skipped rather than silently overwriting it.
    """
    refs = settled_salary_refs(series)
    for f in sorted(facts, key=lambda f: f["sent_at"]):
        kind, sent = f["kind"], f["sent_at"]
        start = f["effective_date"] or sent
        amount = fact_amount(ds, f, home, start)
        upcoming = sorted((x for x in salary if x["date"] >= sent), key=lambda x: x["date"])
        if kind == "income_ended":
            salary[:] = [x for x in salary if x["fixed"] or x["date"] < sent]
        elif kind in ("recurring_salary_amount", "temporary_salary_amount") and amount:
            if not f["effective_date"] and refs and not any(abs(amount - r) <= SALARY_CONFLICT_TOLERANCE * r for r in refs):
                if notes is not None:
                    notes.append(f"skipped {f['message_id']} ({kind}={amount:g}): undated, contradicts settled series {refs}")
                continue
            replaced = [x for x in salary if not x["fixed"] and x["date"] >= start]
            anchor = f["effective_date"] or (replaced[0]["date"] if replaced else None)
            if anchor is None:
                continue
            salary[:] = [x for x in salary if x not in replaced]
            k = 0
            while (when := add_months(anchor, k)) <= end:
                if when >= request_date and not any(x["fixed"] and abs((x["date"] - when).days) <= SALARY_MATCH_DAYS for x in salary):
                    salary.append({"date": when, "amount": amount, "fixed": False, "id": f["message_id"]})
                k += 1
        elif kind == "next_salary_amount" and amount:
            target = min(upcoming, key=lambda x: abs((x["date"] - start).days), default=None)
            if target and not target["fixed"]:
                target["amount"] = amount
                target["date"] = f["effective_date"] or target["date"]
            elif target is None and f["effective_date"]:
                salary.append({"date": start, "amount": amount, "fixed": True, "id": f["message_id"]})
        elif kind == "salary_date_change" and f["effective_date"]:
            # "the next salary arrives on X" moves the whole future payday grid, not just one occurrence.
            movable = [x for x in upcoming if not x["fixed"]]
            if movable:
                base_amount = movable[0]["amount"]
                salary[:] = [x for x in salary if x not in movable]
                k = 0
                while (when := add_months(f["effective_date"], k)) <= end:
                    if when >= request_date:
                        salary.append({"date": when, "amount": base_amount, "fixed": False, "id": f["message_id"]})
                    k += 1
        elif kind == "first_salary" and amount and f["effective_date"]:
            if not any(abs((x["date"] - start).days) <= SALARY_MATCH_DAYS for x in salary):
                salary.append({"date": start, "amount": amount, "fixed": True, "id": f["message_id"]})
        elif kind == "confirmed_one_time_income" and amount:
            when = f["effective_date"] or (upcoming[0]["date"] if upcoming else None)
            if when:
                salary.append({"date": when, "amount": amount, "fixed": True, "id": f["message_id"]})
        elif kind == "expense_change_percent" and f["percent_change"] and f["expense_category"]:
            label = f"series:{f['expense_category'].strip().lower()}"
            factor = 1 + f["percent_change"] / 100
            items[:] = [(d, a * factor if lab == label and d >= sent else a, lab, eid) for d, a, lab, eid in items]
        elif kind == "new_recurring_expense" and amount and f["effective_date"]:
            k = 0
            while (when := add_months(f["effective_date"], k)) <= end:
                if when >= request_date:
                    items.append((when, -amount, f"message:{f['expense_category'] or 'expense'}", f["message_id"]))
                k += 1


@dataclass
class Forecast:
    start: object
    days: int
    balance: float
    min_balance: float
    items: list  # (date, signed_amount, label, event_id)
    series: list
    fact_notes: list = field(default_factory=list)
    safety_buffer: float = 0.0  # calibrated fraction of balance held back on top of min_balance

    @property
    def end(self):
        return self.start + timedelta(days=self.days - 1)

    def lows(self, extra=()):
        """End-of-day balance for each day of the horizon."""
        net = defaultdict(float)
        for d, amount, *_ in [*self.items, *extra]:
            net[d] += amount
        balance, out = self.balance, []
        for i in range(self.days):
            balance += net[self.start + timedelta(days=i)]
            out.append(balance)
        return out

    def safe_on(self, offset, lows=None):
        lows = lows or self.lows()
        effective_min = self.min_balance + self.balance * self.safety_buffer
        if offset and min(lows[:offset]) < effective_min:
            return 0.0
        return max(0.0, min(lows[offset:]) - effective_min)

    def earliest_full(self, amount):
        lows = self.lows()
        for offset in range(self.days):
            if self.safe_on(offset, lows) >= amount - 0.005:
                return self.start + timedelta(days=offset)
        return None


def build_forecast(ds, user_id, request_date, facts=(), cfg=Config()):
    profile = ds.profiles[user_id]
    home = profile["home_currency"]
    events = ds.events[user_id]
    for e in events:
        e["amount_home"] = ds.home_amount(e, home)

    end = request_date + timedelta(days=cfg.horizon_days - 1)
    first_day = request_date if cfg.project_on_request_day else request_date + timedelta(days=1)
    data_end = max(e["date"] for e in events if e["status"] == "settled")
    items, salary = [], []

    for e in events:
        if e["amount_home"] is None or e["status"] not in ("pending", "scheduled"):
            continue
        when = max(e["settles"], request_date)
        if e["direction"] == "debit":
            items.append((when, -e["amount_home"], f"{e['status']}:{e['description']}", e["id"]))
        elif e["status"] == "scheduled" and e["category"] == "salary":
            salary.append({"date": when, "amount": e["amount_home"], "fixed": True, "id": e["id"]})

    for s in [x for x in salary if x["fixed"]]:
        k = 1
        while (when := add_months(s["date"], k)) <= end:
            salary.append({"date": when, "amount": s["amount"], "fixed": False, "id": s["id"]})
            k += 1

    series = detect_series(events, cfg)
    for s in series:
        hits = s["events"]
        anchor = hits[-1]["date"]
        if grid_point(anchor, s["period"], 1) < data_end - timedelta(days=3):
            continue  # series stopped before the data ends
        occurrences, k = [], 1
        while (when := grid_point(anchor, s["period"], k)) <= end:
            k += 1
            if when >= first_day:
                occurrences.append(when)
        amounts = [h["amount_home"] for h in hits]
        if s["key"][2] == "credit":
            amount = stable_amount(amounts)
            if amount is None or "final" in hits[-1]["description"].lower():
                continue
            for when in occurrences:
                if not any(abs((when - x["date"]).days) <= SALARY_MATCH_DAYS for x in salary):
                    salary.append({"date": when, "amount": amount, "fixed": False, "id": hits[-1]["id"]})
        else:
            amount = estimate(amounts, cfg.amount_estimator)
            items += [(when, -amount, f"series:{s['key'][1]}", hits[-1]["id"]) for when in occurrences]

    fact_notes = []
    apply_facts(ds, salary, items, [f for f in facts if f["sent_at"] <= request_date], home, request_date, end, series=series, notes=fact_notes)
    items += [(x["date"], x["amount"], "salary", x["id"]) for x in salary if request_date <= x["date"] <= end]

    return Forecast(
        start=request_date,
        days=cfg.horizon_days,
        balance=float(profile["current_available_balance"]),
        min_balance=float(profile["minimum_balance_to_keep"]),
        items=sorted(items, key=lambda i: (i[0], i[1])),
        series=series,
        fact_notes=fact_notes,
        safety_buffer=cfg.safety_buffer_by_currency.get(home, cfg.safety_buffer_frac),
    )
