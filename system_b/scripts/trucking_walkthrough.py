"""Trucking walkthrough — drive trucking-insurance agents end-to-end and print
the review output. SENDS NOTHING (parity with the CFO walkthrough).

Trucking needs no site research or niche detection: every agent is matched to
brand-new FMCSA carriers in their state (agents are state-licensed), so a
prospect is a `generalist` with a `state`. Leads come from the insurance
pipeline's trucking-leads.json via the adapter.

Run:
  system_b/.venv/bin/python -m system_b.scripts.trucking_walkthrough \
      --inventory path/to/trucking-leads.json \
      --csv path/to/agents.csv        # columns: firm_name,city,state,first_name

With no --csv, a couple of sample agents are used.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from typing import Any

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.trucking import TRUCKING_PACK, trucking_descriptions, trucking_snapshot

SAMPLE_AGENTS: list[dict[str, str]] = [
    {"firm_name": "Lone Star Trucking Insurance", "city": "Dallas", "state": "TX", "first_name": "sam"},
    {"firm_name": "Empire Commercial Auto", "city": "", "state": "NY", "first_name": "dana"},
]


def load_agents(csv_path: str | None) -> list[dict[str, str]]:
    if not csv_path:
        return SAMPLE_AGENTS
    with open(csv_path, newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _prospect(row: dict[str, Any]) -> Prospect:
    return Prospect(
        firm_name=row["firm_name"],
        city=(row.get("city") or "").strip() or None,
        state=(row.get("state") or "").strip() or None,
        classification="generalist",              # trucking matches on geography only
        first_name=(row.get("first_name") or "there").strip() or "there",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="system_b.scripts.trucking_walkthrough")
    parser.add_argument("--inventory", required=True, help="Path to trucking-leads.json")
    parser.add_argument("--csv", default=None, help="Agent CSV (firm_name,city,state,first_name)")
    args = parser.parse_args(argv)

    today = date.today()
    snap = trucking_snapshot(args.inventory, today=today)
    agents = load_agents(args.csv)

    built = 0
    for row in agents:
        prospect = _prospect(row)
        gift = build_gift(prospect, snap, pack=TRUCKING_PACK)
        print("=" * 72)
        print(f"AGENT: {prospect.firm_name}  ({prospect.city or '-'}, {prospect.state or '-'})")
        if gift is None:
            print("  no new carriers in territory — skipped")
            continue
        built += 1
        draft = build_email_1(gift, prospect, trucking_descriptions(gift.leads), today=today, pack=TRUCKING_PACK)
        print(f"  subject: {draft.subject}")
        print(f"  left-field variant: {draft.left_field_variant}")
        print()
        print(draft.body)
        if draft.flags:
            print("\n  flags:")
            for fl in draft.flags:
                print(f"    - {fl}")

    print("=" * 72)
    print(f"built {built}/{len(agents)} review drafts (sent nothing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
