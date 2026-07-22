"""B7 CLI — the quota-driven daily run (stands in for the Track H "Generate"
button). Produces exactly N pending cards: due follow-ups first, then new
first-touches. Sends NOTHING; every card is review_status=pending.

  system_b/.venv/bin/python -m system_b.scripts.sequence_run --emails 12
  system_b/.venv/bin/python -m system_b.scripts.sequence_run --guard   # pause unready follow-ups
"""

from __future__ import annotations

import argparse
from datetime import date

from system_b import config
from system_b.clients.airtable_client import AirtableClient
from system_b.sequence import guard_unready_followups, quota_run


def main() -> None:
    ap = argparse.ArgumentParser(description="Quota-driven sequence run (pending cards only).")
    ap.add_argument("--emails", type=int, default=config.REVIEW_CAPACITY_PER_DAY,
                    help="how many email messages to generate this run")
    ap.add_argument("--pack", type=str, default="cfo", help="default NichePack for new first-touches")
    ap.add_argument("--guard", action="store_true",
                    help="pause Smartlead leads whose follow-up isn't ready in time (B5), then exit")
    args = ap.parse_args()

    config.require("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID")
    at = AirtableClient()
    at.ensure_schema()

    if args.guard:
        config.require("SMARTLEAD_API_KEY")
        from system_b.sending import SmartleadSender
        sender = SmartleadSender()
        paused = guard_unready_followups(at, sender, date.today())
        print(f"[guard] paused {len(paused)} unready follow-up(s): {paused}")
        at.close()
        return

    config.require("OPENAI_API_KEY")
    print("[run] generating cards (per-niche inventory built on demand)...")
    summary = quota_run(
        at, email_quota=args.emails, pack_default=args.pack, today=date.today()
    )
    at.close()

    print(
        f"\n[done] generated {summary['generated']}/{summary['quota']} card(s) "
        f"(cap {summary['capped_at']}): {summary['first_touches']} first-touch, "
        f"{summary['followups']} follow-up. All review_status=pending — approve by hand."
    )
    for r in summary["results"]:
        step = r.get("step", "?")
        print(f"  · {r.get('firm','?'):32} step={step} {r.get('status')}"
              + (f" [{r.get('kind')}]" if r.get("kind") else ""))


if __name__ == "__main__":
    main()
