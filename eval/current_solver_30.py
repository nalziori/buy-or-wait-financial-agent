"""Current deterministic solver's predictions for the 30 audited evaluation requests, for comparison
against the independent Sonnet pass. Uses only cached Gemini facts already on disk -- no new API calls.

Usage:
    python eval/current_solver_30.py
"""
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from data import Dataset  # noqa: E402
from evidence import extract_message_facts, resolve_image_amounts  # noqa: E402
from forecast import build_forecast  # noqa: E402
from llm import LLM  # noqa: E402
from main import row_for  # noqa: E402
from planner import decide  # noqa: E402

IDS_FILE = Path(__file__).resolve().parent.parent / "evaluation" / "sonnet_30_request_ids.txt"
OUT_FILE = Path(__file__).resolve().parent.parent / "evaluation" / "current_solver_30.csv"


def main():
    ids = [line.strip() for line in IDS_FILE.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]

    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    resolve_image_amounts(ds, llm)
    facts = extract_message_facts(ds, llm)

    by_id = {r["request_id"]: r for r in ds.requests}
    rows = []
    for rid in ids:
        r = by_id[rid]
        rd = date.fromisoformat(r["request_date"])
        f = build_forecast(ds, r["user_id"], rd, facts.get(r["user_id"], []))
        row = row_for(decide(ds, r, f))
        rows.append({"request_id": rid, "request_type": r["request_type"], **row})

    with open(OUT_FILE, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT_FILE} (0 new Gemini calls -- all served from cache)")


if __name__ == "__main__":
    main()
