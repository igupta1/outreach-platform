"""Bookkeeping walkthrough — drive bookkeeping/accounting firms end-to-end and
print the review output. SENDS NOTHING (parity with the CFO walkthrough).

Like trucking, bookkeeping needs no site research: every firm is matched to
small companies in its area that just posted a junior finance role, so a
prospect is a `generalist` with a `city`/`state`. Leads come from the cfo
pipeline's bookkeeping-leads.json via the adapter.

Run:
  system_b/.venv/bin/python -m system_b.scripts.bookkeeping_walkthrough \
      --inventory path/to/bookkeeping-leads.json \
      --csv path/to/firms.csv        # columns: firm_name,city,state,first_name
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from typing import Any

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.bookkeeping import (
    BOOKKEEPING_PACK,
    bookkeeping_descriptions,
    bookkeeping_snapshot,
)

SAMPLE_FIRMS: list[dict[str, str]] = [
    {"firm_name": "Hill Country Bookkeeping", "city": "Austin", "state": "TX", "first_name": "mia"},
    {"firm_name": "Bay Area Books", "city": "", "state": "CA", "first_name": "reid"},
]


def load_firms(csv_path: str | None) -> list[dict[str, str]]:
    if not csv_path:
        return SAMPLE_FIRMS
    with open(csv_path, newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _prospect(row: dict[str, Any]) -> Prospect:
    return Prospect(
        firm_name=row["firm_name"],
        city=(row.get("city") or "").strip() or None,
        state=(row.get("state") or "").strip() or None,
        classification="generalist",
        first_name=(row.get("first_name") or "there").strip() or "there",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="system_b.scripts.bookkeeping_walkthrough")
    parser.add_argument("--inventory", required=True, help="Path to bookkeeping-leads.json")
    parser.add_argument("--csv", default=None, help="Firm CSV (firm_name,city,state,first_name)")
    args = parser.parse_args(argv)

    today = date.today()
    snap = bookkeeping_snapshot(args.inventory, today=today)
    firms = load_firms(args.csv)

    built = 0
    for row in firms:
        prospect = _prospect(row)
        gift = build_gift(prospect, snap, pack=BOOKKEEPING_PACK)
        print("=" * 72)
        print(f"FIRM: {prospect.firm_name}  ({prospect.city or '-'}, {prospect.state or '-'})")
        if gift is None:
            print("  no junior finance hires in territory — skipped")
            continue
        built += 1
        draft = build_email_1(gift, prospect, bookkeeping_descriptions(gift.leads), today=today, pack=BOOKKEEPING_PACK)
        print(f"  subject: {draft.subject}")
        print(f"  left-field variant: {draft.left_field_variant}")
        print()
        print(draft.body)
        if draft.flags:
            print("\n  flags:")
            for fl in draft.flags:
                print(f"    - {fl}")

    print("=" * 72)
    print(f"built {built}/{len(firms)} review drafts (sent nothing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
