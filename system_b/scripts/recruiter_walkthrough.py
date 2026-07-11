"""Recruiter walkthrough — drive staffing agencies end-to-end and print the
review output. SENDS NOTHING (parity with the CFO walkthrough).

A recruiter prospect carries an optional `function` (their specialty): with it,
they're matched to heavy hirers in that function (geo fallback if none nearby);
without it, a generalist geo match. Leads come from the recruiter pipeline's
recruiter-leads.json via the adapter.

Run:
  system_b/.venv/bin/python -m system_b.scripts.recruiter_walkthrough \
      --inventory path/to/recruiter-leads.json \
      --csv path/to/agencies.csv   # columns: firm_name,city,state,first_name,function
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from typing import Any

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.niches.recruiter import (
    RECRUITER_PACK,
    recruiter_descriptions,
    recruiter_prospect,
    recruiter_snapshot,
)

SAMPLE_AGENCIES: list[dict[str, str]] = [
    {"firm_name": "FinHire Staffing", "city": "", "state": "TX", "first_name": "lee", "function": "finance"},
    {"firm_name": "Lone Star Staffing", "city": "", "state": "TX", "first_name": "dana", "function": ""},
]


def load_agencies(csv_path: str | None) -> list[dict[str, str]]:
    if not csv_path:
        return SAMPLE_AGENCIES
    with open(csv_path, newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="system_b.scripts.recruiter_walkthrough")
    parser.add_argument("--inventory", required=True, help="Path to recruiter-leads.json")
    parser.add_argument("--csv", default=None, help="Agency CSV (firm_name,city,state,first_name,function)")
    args = parser.parse_args(argv)

    today = date.today()
    snap = recruiter_snapshot(args.inventory, today=today)
    agencies = load_agencies(args.csv)

    built = 0
    for row in agencies:
        prospect = recruiter_prospect(
            row["firm_name"], city=row.get("city") or None, state=row.get("state") or None,
            function=row.get("function") or None, first_name=row.get("first_name") or "there",
        )
        gift = build_gift(prospect, snap, pack=RECRUITER_PACK)
        print("=" * 72)
        spec = (prospect.match_param[1] if prospect.match_param else "generalist")
        print(f"AGENCY: {prospect.firm_name}  ({prospect.state or '-'}, {spec})")
        if gift is None:
            print("  no heavy hirers in territory — skipped")
            continue
        built += 1
        draft = build_email_1(gift, prospect, recruiter_descriptions(gift.leads), today=today, pack=RECRUITER_PACK)
        print(f"  subject: {draft.subject}")
        print()
        print(draft.body)

    print("=" * 72)
    print(f"built {built}/{len(agencies)} review drafts (sent nothing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
