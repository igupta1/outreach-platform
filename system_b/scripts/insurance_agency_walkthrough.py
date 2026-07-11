"""Insurance-agency walkthrough — one entry point, routed to trucking or P&C
per agency. SENDS NOTHING.

Each agency row carries a `subniche` (trucking|pc) or a `focus` text the router
keyword-classifies. The router picks the pack + inventory; the engine + copy do
the rest. Needs both sub-inventories.

Run:
  system_b/.venv/bin/python -m system_b.scripts.insurance_agency_walkthrough \
      --trucking-inventory trucking-leads.json --pc-inventory pc-leads.json \
      --csv agencies.csv     # columns: firm_name,city,state,first_name,subniche|focus
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from typing import Any

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches import insurance_agency as router

SAMPLE_AGENCIES: list[dict[str, str]] = [
    {"firm_name": "Lone Star Trucking Insurance", "state": "TX", "first_name": "sam", "focus": "commercial trucking and motor carrier"},
    {"firm_name": "Golden State Commercial", "state": "CA", "first_name": "ana", "focus": "general liability and workers comp"},
]


def load_agencies(csv_path: str | None) -> list[dict[str, str]]:
    if not csv_path:
        return SAMPLE_AGENCIES
    with open(csv_path, newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _subniche(row: dict[str, Any]) -> str:
    return (row.get("subniche") or "").strip().lower() or router.classify_subniche(row.get("focus"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="system_b.scripts.insurance_agency_walkthrough")
    parser.add_argument("--trucking-inventory", required=True)
    parser.add_argument("--pc-inventory", required=True)
    parser.add_argument("--csv", default=None)
    args = parser.parse_args(argv)

    today = date.today()
    paths = {router.TRUCKING: args.trucking_inventory, router.PC: args.pc_inventory}
    snapshots: dict[str, Any] = {}

    built = 0
    agencies = load_agencies(args.csv)
    for row in agencies:
        sub = _subniche(row)
        pack, snapshot_fn, descriptions_fn = router.route(sub)
        snap = snapshots.get(sub) or snapshots.setdefault(sub, snapshot_fn(paths[sub], today=today))
        prospect = Prospect(
            firm_name=row["firm_name"],
            city=(row.get("city") or "").strip() or None,
            state=(row.get("state") or "").strip() or None,
            classification="generalist",
            first_name=(row.get("first_name") or "there").strip() or "there",
        )
        gift = build_gift(prospect, snap, pack=pack)
        print("=" * 72)
        print(f"AGENCY: {prospect.firm_name}  ({prospect.state or '-'})  -> {sub}")
        if gift is None:
            print("  no leads in territory — skipped")
            continue
        built += 1
        draft = build_email_1(gift, prospect, descriptions_fn(gift.leads), today=today, pack=pack)
        print(f"  subject: {draft.subject}")
        print()
        print(draft.body)

    print("=" * 72)
    print(f"built {built}/{len(agencies)} review drafts (sent nothing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
