"""Deterministic stratified sample of 30 evaluation requests (dataset/requests.csv, no ground truth)
for an independent disagreement audit. Uses only raw dataset fields -- never our solver's output or
any hypothesis about where it might be wrong -- so selection cannot be biased toward known weak spots.

Usage:
    python eval/select_audit_sample.py
Writes:
    evaluation/sonnet_30_request_ids.txt
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))
from data import Dataset  # noqa: E402

SEED = 42
TARGET_N = 30
STOP_FLEX = {"stoppable", "reducible_or_stoppable"}
REDUCE_FLEX = {"reducible", "reducible_or_stoppable"}


def features(ds, r):
    uid = r["user_id"]
    profile = ds.profiles[uid]
    home = profile["home_currency"]
    events = ds.events[uid]
    user_messages = ds.messages.get(uid, [])
    request_images = [i for i in ds.images if i["request_id"] == r["request_id"]]
    options = ds.options.get(r["request_id"], [])

    salary_keywords = ("salary", "gaji", "pay", "income", "payroll", "wage")
    salary_signal = any(any(k in m["message_text"].lower() for k in salary_keywords) for m in user_messages)

    flexible_signal = bool(
        (profile["expense_categories_user_is_willing_to_reduce"] or "").strip()
        or (profile["expense_categories_user_is_willing_to_stop"] or "").strip()
    )

    debit_flex = [e["flexibility"] for e in events if e["direction"] == "debit"]
    variable_heavy = debit_flex and sum(f in STOP_FLEX | REDUCE_FLEX for f in debit_flex) / len(debit_flex) >= 0.5
    fixed_heavy = debit_flex and sum(f == "fixed" for f in debit_flex) / len(debit_flex) >= 0.7

    requested_home = float(r["requested_amount"])  # requested_amount is already stated in home_currency
    slack = float(profile["current_available_balance"]) - float(profile["minimum_balance_to_keep"])
    near_boundary = slack != 0 and 0.7 <= requested_home / slack <= 1.3

    return {
        "request_type": r["request_type"],
        "home_currency": home,
        "has_message": bool(user_messages),
        "has_image": bool(request_images),
        "salary_signal": salary_signal,
        "flexible_signal": flexible_signal,
        "has_installments": any(o["payment_method"] == "installments" for o in options),
        "allows_partial": r["allows_partial_payment"].strip().lower() == "true",
        "near_boundary": near_boundary,
        "variable_heavy": bool(variable_heavy),
        "fixed_heavy": bool(fixed_heavy),
    }


def main():
    ds = Dataset()
    feats = {r["request_id"]: features(ds, r) for r in ds.requests}
    ids = [r["request_id"] for r in ds.requests]

    buckets = [
        lambda f: f["has_message"] and f["has_image"],
        lambda f: not f["has_message"] and not f["has_image"],
        lambda f: f["salary_signal"],
        lambda f: f["flexible_signal"],
        lambda f: f["has_installments"],
        lambda f: f["allows_partial"],
        lambda f: f["near_boundary"],
        lambda f: f["variable_heavy"],
        lambda f: f["fixed_heavy"],
    ]

    rng = random.Random(SEED)
    selected = []
    seen = set()

    # 1) cover every distinct request_type and home_currency at least once.
    for key in ("request_type", "home_currency"):
        values = sorted({f[key] for f in feats.values()})
        for v in values:
            pool = [i for i in ids if feats[i][key] == v and i not in seen]
            if pool:
                rng.shuffle(pool)
                selected.append(pool[0])
                seen.add(pool[0])

    # 2) cover each condition bucket with up to 2 more examples.
    for bucket in buckets:
        pool = [i for i in ids if bucket(feats[i]) and i not in seen]
        rng.shuffle(pool)
        for i in pool[:2]:
            if len(selected) >= TARGET_N:
                break
            selected.append(i)
            seen.add(i)

    # 3) top up to exactly TARGET_N with a plain deterministic random sample of the rest.
    remaining = [i for i in ids if i not in seen]
    rng.shuffle(remaining)
    selected += remaining[: max(0, TARGET_N - len(selected))]
    selected = selected[:TARGET_N]
    selected.sort(key=lambda i: int(i.split("_")[1]))

    out = Path(__file__).resolve().parent.parent / "evaluation" / "sonnet_30_request_ids.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"# seed={SEED}, n={len(selected)}\n" + "\n".join(selected) + "\n", encoding="utf-8")
    print(f"Selected {len(selected)} requests -> {out}")
    for i in selected:
        print(f"  {i:<12} {feats[i]}")


if __name__ == "__main__":
    main()
