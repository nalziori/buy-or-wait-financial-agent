"""Buy or Wait? entry point.

    python code/main.py            # dataset/requests.csv -> output.csv (repo root) + code/evaluation/usage_report.md
    python code/main.py --samples  # dataset/sample_requests.csv -> eval/sample_predictions.csv
"""
import argparse
import csv
from datetime import date

from data import REPO_ROOT, Dataset
from evidence import extract_message_facts, resolve_image_amounts
from forecast import build_forecast
from llm import LLM
from planner import decide, explain

COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def number(amount):
    amount = round(amount, 2)
    return str(int(amount)) if abs(amount - round(amount)) < 0.005 else f"{amount:.2f}".rstrip("0").rstrip(".")


def plan_amount(amount):
    amount = round(amount, 2)
    return str(int(amount)) if abs(amount - round(amount)) < 0.005 else f"{amount:.2f}"


def row_for(decision):
    plan = decision["plan"]
    payments = "|".join(f"{d.isoformat()}:{plan_amount(a)}" for d, a in plan.payments) if plan else "none"
    changes = (
        "|".join(f"stop:{eid}" if action == "stop" else f"reduce_to:{eid}:{plan_amount(floor)}" for action, eid, floor, _ in plan.changes)
        if plan and plan.changes
        else "none"
    )
    return {
        "amount_safe_to_pay": number(decision["amount_safe_to_pay"]),
        "affordability_status": decision["affordability_status"],
        "recommended_payment_method": decision["recommended_payment_method"],
        "payment_plan": payments,
        "earliest_date_for_full_payment": decision["earliest"].isoformat() if decision["earliest"] else "",
        "spending_changes_needed": changes,
        "decision_explanation": explain(decision),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", action="store_true", help="Predict sample_requests.csv for local scoring")
    parser.add_argument("--no-llm", action="store_true", help="Skip image/message extraction (no API calls); writes to eval/ only")
    args = parser.parse_args()

    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    image_notes = {} if args.no_llm else resolve_image_amounts(ds, llm)
    facts = {} if args.no_llm else extract_message_facts(ds, llm)

    requests = ds.samples if args.samples else ds.requests
    rows = []
    for request in requests:
        request_date = date.fromisoformat(request["request_date"])
        forecast = build_forecast(ds, request["user_id"], request_date, facts.get(request["user_id"], []))
        rows.append({"request_id": request["request_id"], **row_for(decide(ds, request, forecast))})

    if args.no_llm:
        out_path = REPO_ROOT / "eval" / ("sample_predictions_no_llm.csv" if args.samples else "predictions_no_llm.csv")
    else:
        out_path = REPO_ROOT / ("eval/sample_predictions.csv" if args.samples else "output.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    if not args.samples and not args.no_llm:
        llm.write_usage_report(REPO_ROOT / "evaluation" / "usage_report.md", len(requests))
    print(f"Wrote {len(rows)} rows to {out_path} ({len(image_notes)} image amounts, {sum(map(len, facts.values()))} message facts)")


if __name__ == "__main__":
    main()
