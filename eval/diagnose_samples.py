"""Per-request diagnostic dump for root-cause classification: applied facts + forecast trough composition.

Usage:
    python eval/diagnose_samples.py request_02 request_06 ...
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
from planner import change_candidates, decide  # noqa: E402


def main():
    ds = Dataset()
    llm = LLM(model="gemini-3.5-flash")
    resolve_image_amounts(ds, llm)
    facts = extract_message_facts(ds, llm)

    targets = sys.argv[1:] or [s["request_id"] for s in ds.samples]
    for rid in targets:
        s = next(x for x in ds.samples if x["request_id"] == rid)
        uid = s["user_id"]
        rd = date.fromisoformat(s["request_date"])
        user_facts = facts.get(uid, [])
        f = build_forecast(ds, uid, rd, user_facts)
        lows = f.lows()
        trough = lows.index(min(lows))

        print(f"\n===== {rid} {uid} request_date={rd} requested={s['requested_amount']} desired={s['desired_completion_date']} partial={s['allows_partial_payment']}")
        print(f"  balance={f.balance} min_balance={f.min_balance}")
        print(f"  GOLD:  safe={s['amount_safe_to_pay']} status={s['affordability_status']} method={s['recommended_payment_method']} plan={s['payment_plan']} earliest={s['earliest_date_for_full_payment'] or '-'} changes={s['spending_changes_needed']}")
        print(f"         expl: {s['decision_explanation']}")
        decision = decide(ds, s, f)
        from main import row_for
        row = row_for(decision)
        print(f"  PRED:  safe={row['amount_safe_to_pay']} status={row['affordability_status']} method={row['recommended_payment_method']} plan={row['payment_plan']} earliest={row['earliest_date_for_full_payment'] or '-'} changes={row['spending_changes_needed']}")
        print(f"         expl: {row['decision_explanation']}")
        print(f"  trough day={trough} date={f.start + timedelta(days=trough)} low_balance={lows[trough]:.2f} (min_required={f.min_balance})")

        print("  applied message facts for this user (sent_at <= request_date):")
        relevant = [ft for ft in user_facts if ft["sent_at"] and ft["sent_at"] <= rd]
        if not relevant:
            print("    (none)")
        for ft in relevant:
            print(f"    {ft['message_id']} sent={ft['sent_at']} kind={ft['kind']} amount={ft['amount']} currency={ft['currency']} eff={ft['effective_date']} pct={ft['percent_change']} cat={ft['expense_category']}")
        print("  ALL message facts for this user (incl. future / not applied):")
        for ft in user_facts:
            if ft not in relevant:
                print(f"    {ft['message_id']} sent={ft['sent_at']} kind={ft['kind']} amount={ft['amount']} currency={ft['currency']} eff={ft['effective_date']} (not <= request_date)")

        print("  detected recurring series (key, period, n, last_date, amounts_used):")
        for sr in f.series:
            amounts = [h["amount_home"] for h in sr["events"]]
            print(f"    {sr['key']} period={sr['period']} n={len(amounts)} last={sr['events'][-1]['date']} amounts_last4={[round(a,2) for a in amounts[-4:]]}")

        print(f"  items up to trough (day<={trough}):")
        by_label = defaultdict(lambda: [0, 0.0])
        for d, amt, label, eid in f.items:
            day = (d - f.start).days
            if day <= trough:
                by_label[(label, eid)][0] += 1
                by_label[(label, eid)][1] += amt
        for (label, eid), (cnt, total) in sorted(by_label.items(), key=lambda kv: kv[1][1]):
            print(f"    {label:<30} n={cnt:<3} total={total:>14.2f}  event={eid}")

        events_by_id = {e["id"]: e for e in ds.events[uid]}
        profile = ds.profiles[uid]
        cands = change_candidates(f, events_by_id, profile)
        print(f"  spending-change candidates (protect={profile['expense_categories_to_protect']}, reduce_ok={profile['expense_categories_user_is_willing_to_reduce']}, stop_ok={profile['expense_categories_user_is_willing_to_stop']}):")
        for action, eid, floor, desc, occ in cands:
            print(f"    {action:<10} {eid} floor={floor} desc={desc} occurrences_in_window={len(occ)} total_cut={sum(a for _, a in occ):.2f}")

        print(f"  options on file:")
        for o in ds.options.get(rid, []):
            print(f"    {o['payment_option_id']} {o['payment_method']} amt={o['payment_amount']} n={o['number_of_payments']} start={o['first_payment_date']} freq={o['payment_frequency_days']}")


if __name__ == "__main__":
    main()
