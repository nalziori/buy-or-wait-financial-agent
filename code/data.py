"""Dataset loading: typed events per user, requests, options, messages, and dated FX conversion."""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT / "dataset"
BRIDGE_CURRENCIES = ("USD", "EUR")


def read_csv(name):
    with open(DATASET / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(value):
    return float(value) if value not in ("", None) else None


def to_date(value):
    return date.fromisoformat(value[:10]) if value else None


def group_by(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row[key]].append(row)
    return grouped


def _pair(table, src, dst):
    if (src, dst) in table:
        return table[(src, dst)]
    if (dst, src) in table:
        return 1 / table[(dst, src)]
    return None


class FX:
    """Dated rates. Closest rate date first; direct pair, inverse, then one bridge currency."""

    def __init__(self, rows):
        self.tables = defaultdict(dict)
        for r in rows:
            self.tables[to_date(r["rate_date"])][(r["from_currency"], r["to_currency"])] = float(r["rate"])

    def rate(self, src, dst, day):
        if src == dst:
            return 1.0
        for rate_day in sorted(self.tables, key=lambda d: (abs((d - day).days), d > day)):
            table = self.tables[rate_day]
            direct = _pair(table, src, dst)
            if direct is not None:
                return direct
            for bridge in BRIDGE_CURRENCIES:
                a, b = _pair(table, src, bridge), _pair(table, bridge, dst)
                if a is not None and b is not None:
                    return a * b
        raise KeyError(f"No FX path {src}->{dst} near {day}")


def parse_event(r):
    return {
        "id": r["event_id"],
        "user": r["user_id"],
        "type": r["event_type"],
        "category": r["category"],
        "description": r["description"],
        "direction": r["direction"],
        "amount": to_float(r["amount"]),
        "currency": r["currency"],
        "date": to_date(r["event_date"]),
        "settles": to_date(r["settlement_date"]) or to_date(r["event_date"]),
        "status": r["status"],
        "linked": r["linked_event_id"] or None,
        "flexibility": r["flexibility"],
        "floor": to_float(r["minimum_allowed_amount"]),
    }


class Dataset:
    def __init__(self):
        rates = read_csv("exchange_rates.csv")
        self.fx = FX(rates)
        self.currencies = {r["from_currency"] for r in rates} | {r["to_currency"] for r in rates}
        self.profiles = {r["user_id"]: r for r in read_csv("financial_profiles.csv")}
        self.events = defaultdict(list)
        for r in read_csv("financial_events.csv"):
            self.events[r["user_id"]].append(parse_event(r))
        self.requests = read_csv("requests.csv")
        self.samples = read_csv("sample_requests.csv")
        self.options = group_by(read_csv("request_payment_options.csv"), "request_id")
        self.messages = group_by(read_csv("messages.csv"), "user_id")
        self.images = read_csv("images.csv")

    def home_amount(self, event, home_currency):
        if event["amount"] is None:
            return None
        return event["amount"] * self.fx.rate(event["currency"], home_currency, event["settles"])
