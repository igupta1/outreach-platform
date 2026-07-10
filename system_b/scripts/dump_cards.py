"""Dump every prospect's assembled review card from Airtable into one text
file, for external review. No LLM, no scraper — just reads the rows the
walkthrough already wrote (review_card / queued_message / flags).

Rows with no gift (and therefore no card) are listed at the end so the file
accounts for every prospect.

Run:  system_b/.venv/bin/python -m system_b.scripts.dump_cards --out system_b/review_cards.txt
"""

from __future__ import annotations

import argparse

from system_b import config
from system_b.clients.airtable_client import AirtableClient

_RULE = "#" * 80


def main() -> None:
    ap = argparse.ArgumentParser(description="Dump all Airtable review cards to a text file.")
    ap.add_argument("--out", default="system_b/review_cards.txt")
    args = ap.parse_args()

    config.require("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID")
    at = AirtableClient()
    rows = at.table.all(max_records=1000)
    at.close()

    rows.sort(key=lambda r: (r.get("fields", {}).get("firm_name") or "").lower())

    written = 0
    no_card: list[str] = []
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            fields = r.get("fields", {})
            firm = fields.get("firm_name", "(unknown)")
            card = fields.get("review_card")
            if not card:
                no_card.append(firm)
                continue
            written += 1
            f.write(f"\n\n{_RULE}\n# CARD {written}: {firm}\n{_RULE}\n{card}\n")

        if no_card:
            f.write(f"\n\n{_RULE}\n# {len(no_card)} PROSPECT(S) WITH NO CARD (no gift / not processed):\n{_RULE}\n")
            for firm in no_card:
                f.write(f"#   {firm}\n")

    print(f"wrote {written} cards to {args.out} ({len(no_card)} without a card)")


if __name__ == "__main__":
    main()
