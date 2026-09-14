"""Plan generation, ranking, and templated explanations for one request on top of a Forecast."""
import math
from dataclasses import dataclass, field
from datetime import timedelta
from itertools import combinations

EPS = 0.005
STOP_FLEX = {"stoppable", "reducible_or_stoppable"}
REDUCE_FLEX = {"reducible", "reducible_or_stoppable"}


@dataclass
class Plan:
    method: str
    payments: list  # [(date, amount)]
    changes: list = field(default_factory=list)  # [(action, event_id, floor_or_None, description)]
    option_id: str = ""

    @property
    def total(self):
        return round(sum(a for _, a in self.payments), 2)

    def rank(self, desired):
        return (
            self.payments[-1][0] > desired,
            bool(self.changes),
            self.total,
            self.payments[0][0],
            len(self.payments),
            int(self.option_id.rsplit("_", 1)[-1]) if self.option_id else math.inf,
        )


def split(value):
    return {v for v in (value or "").split("|") if v}


def is_safe(forecast, payments, adjustments=()):
    extra = [(d, -a) for d, a in payments] + list(adjustments)
    effective_min = forecast.min_balance + forecast.balance * forecast.safety_buffer
    return min(forecast.lows(extra)) >= effective_min - EPS


def change_candidates(forecast, events_by_id, profile):
    """Allowed (action, event_id, floor, description, adjustments) for projected flexible series in the window."""
    protected = split(profile["expense_categories_to_protect"])
    reduce_ok = split(profile["expense_categories_user_is_willing_to_reduce"]) - protected
    stop_ok = split(profile["expense_categories_user_is_willing_to_stop"]) - protected
    occurrences = {}
    for d, amount, label, eid in forecast.items:
        if label.startswith("series:") and amount < 0:
            occurrences.setdefault(eid, []).append((d, -amount))
    out = []
    for eid, occ in occurrences.items():
        event = events_by_id[eid]
        category, flex, floor = event["category"], event["flexibility"], event["floor"]
        if flex in STOP_FLEX and category in stop_ok:
            out.append(("stop", eid, None, event["description"], [(d, a) for d, a in occ]))
        if flex in REDUCE_FLEX and category in reduce_ok and floor is not None and occ[0][1] > floor + EPS:
            out.append(("reduce_to", eid, floor, event["description"], [(d, a - floor) for d, a in occ]))
    return out


def cheapest_changes(forecast, payments, candidates):
    """Smallest total in-window spending cut (up to 3 changes, one per event) that makes the payments safe."""
    best = None
    for size in (1, 2, 3):
        for combo in combinations(candidates, size):
            if len({c[1] for c in combo}) < size:
                continue
            adjustments = [adj for c in combo for adj in c[4]]
            if not is_safe(forecast, payments, adjustments):
                continue
            key = (round(sum(a for _, a in adjustments), 2), size, sorted(c[1] for c in combo))
            if best is None or key < best[0]:
                best = (key, combo)
    if best is None:
        return None
    return [(c[0], c[1], c[2], c[3]) for c in sorted(best[1], key=lambda c: int(c[1].rsplit("_", 1)[-1]))]


def installment_schedule(option):
    first = option["first_payment_date"]
    count = int(option["number_of_payments"])
    step = int(option["payment_frequency_days"] or 0)
    return [(first + timedelta(days=step * k), float(option["payment_amount"])) for k in range(count)]


def decide(ds, request, forecast):
    from data import to_date

    profile = ds.profiles[request["user_id"]]
    methods = split(profile["payment_methods_user_will_consider"])
    max_months = float(profile["max_installment_months"]) if profile["max_installment_months"] else 0
    today, desired = forecast.start, to_date(request["desired_completion_date"])
    requested = float(request["requested_amount"])
    safe_today = round(min(requested, forecast.safe_on(0)), 2)
    earliest = forecast.earliest_full(requested)
    events_by_id = {e["id"]: e for e in ds.events[request["user_id"]]}
    candidates = change_candidates(forecast, events_by_id, profile)

    base_plans = []
    if "full_payment" in methods:
        base_plans.append(Plan("full_payment", [(today, requested)]))
    if "installments" in methods:
        for option in ds.options.get(request["request_id"], []):
            if option["payment_method"] != "installments":
                continue
            option = {**option, "first_payment_date": to_date(option["first_payment_date"])}
            schedule = installment_schedule(option)
            months = int(option["number_of_payments"]) * int(option["payment_frequency_days"] or 30) / 30.4
            if months <= max_months + 0.5 and schedule[-1][0] <= desired:
                base_plans.append(Plan("installments", schedule, option_id=option["payment_option_id"]))

    safe_plans = []
    for plan in base_plans:
        if is_safe(forecast, plan.payments):
            safe_plans.append(plan)
        else:
            changes = cheapest_changes(forecast, plan.payments, candidates)
            if changes:
                adjusted = Plan(plan.method, plan.payments, changes, plan.option_id)
                safe_plans.append(adjusted)

    partial_eligible = "partial_payment" in methods and request["allows_partial_payment"].strip().lower() == "true"
    if (
        partial_eligible
        and 0 < safe_today < requested
        and earliest
        and today < earliest <= desired
    ):
        plan = Plan("partial_payment", [(today, safe_today), (earliest, round(requested - safe_today, 2))])
        if is_safe(forecast, plan.payments):
            safe_plans.append(plan)

    if "full_payment" in methods and earliest and today < earliest <= desired:
        safe_plans.append(Plan("wait", [(earliest, requested)]))

    safe_plans = [p for p in safe_plans if p.payments[-1][0] <= desired]
    best = min(safe_plans, key=lambda p: p.rank(desired)) if safe_plans else None

    if best is None:
        status, method = "not_affordable", "not_recommended"
    elif best.method == "full_payment" and not best.changes:
        status, method = "affordable_now", "full_payment"
    elif best.method == "wait":
        status, method = "affordable_later", "wait"
    else:
        status, method = "affordable_with_plan", best.method

    return {
        "amount_safe_to_pay": safe_today,
        "affordability_status": status,
        "recommended_payment_method": method,
        "plan": best,
        "earliest": earliest if status != "not_affordable" else None,
        "capacity_earliest": earliest,
        "partial_eligible": partial_eligible,
        "requested": requested,
        "desired": desired,
        "currency": profile["home_currency"],
        "min_balance": forecast.min_balance,
    }


def money(currency, amount):
    amount = round(amount, 2)
    text = f"{amount:,.0f}" if abs(amount - round(amount)) < 0.005 else f"{amount:,.2f}"
    return f"{currency} {text}"


def long_date(d):
    return f"{d.day} {d.strftime('%B %Y')}"


def explain(decision):
    cur, plan = decision["currency"], decision["plan"]
    minimum = money(cur, decision["min_balance"])
    method = decision["recommended_payment_method"]
    if method == "not_recommended":
        if decision["partial_eligible"] and decision["amount_safe_to_pay"] > 0 and decision["capacity_earliest"] is None:
            return (
                f"Do not proceed with the {money(cur, decision['requested'])} request. Although "
                f"{money(cur, decision['amount_safe_to_pay'])} is available today, the full amount cannot be "
                f"completed safely within 90 days."
            )
        return (
            f"Do not make this payment by {long_date(decision['desired'])}. None of the available options keeps "
            f"the {minimum} minimum protected."
        )
    if method == "wait":
        d, amount = plan.payments[0]
        return f"Pay {money(cur, amount)} in full on {long_date(d)}. Paying earlier would take the balance below the {minimum} minimum."
    if method == "partial_payment":
        (d1, a1), (d2, a2) = plan.payments
        return (
            f"Pay {money(cur, a1)} today and the remaining {money(cur, a2)} on {long_date(d2)}. This completes the "
            f"full request and keeps the {minimum} minimum protected."
        )
    prefix = ""
    if plan.changes:
        parts = [
            f"stop the {desc.lower()}" if action == "stop" else f"reduce the {desc.lower()} to {money(cur, floor)}"
            for action, _, floor, desc in plan.changes
        ]
        prefix = (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]).capitalize() + ", then "
    if method == "installments":
        d, amount = plan.payments[0]
        body = f"use {len(plan.payments)} installments of {money(cur, amount)}, starting {long_date(d)}"
    else:
        body = f"pay {money(cur, plan.payments[0][1])} today"
    sentence = prefix + body if prefix else body[0].upper() + body[1:]
    return f"{sentence}. This leaves at least {minimum} available{' over the next 90 days' if not plan.changes and method == 'full_payment' else ''}."
