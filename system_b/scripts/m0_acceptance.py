"""M0 acceptance test.

1. Query the live scraper for a known niche (+ the taxonomy).
2. Ensure the Airtable Prospects schema exists (create it programmatically).
3. Write a stub prospect row.

Run:  system_b/.venv/bin/python -m system_b.scripts.m0_acceptance
"""

from __future__ import annotations

from system_b import config
from system_b.clients.airtable_client import AirtableClient
from system_b.clients.scraper_client import ScraperClient


def main() -> None:
    config.require("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID")

    # 1) Live scraper query for a known niche.
    with ScraperClient() as sc:
        taxonomy = sc.niches()
        leads = sc.leads(industry="healthcare", freshness="fresh", limit=3)
    print(f"[scraper] taxonomy parents: {len(taxonomy)} | healthcare/fresh leads: {len(leads)}")
    for l in leads:
        print(f"          {l.company} [{l.signal_type}] niche={l.niche} {l.city},{l.state}")
    assert taxonomy, "taxonomy empty"

    # 2) Ensure the Airtable schema.
    at = AirtableClient()
    summary = at.ensure_schema()
    print(f"[airtable] schema: {summary}")

    # 3) Write a stub prospect row.
    stub = {
        "firm_name": "M0 Stub Firm (safe to delete)",
        "stage": "researched",
        "classification": "generalist",
        "city": "Denver",
        "state": "CO",
        "review_status": "pending",
        "flags": "M0 acceptance stub row",
    }
    existing = at.find_by_firm(stub["firm_name"])
    if existing:
        rec = at.update(existing["id"], stub)
        print(f"[airtable] updated existing stub row: {rec['id']}")
    else:
        rec = at.create_prospect(stub)
        print(f"[airtable] wrote stub prospect row: {rec['id']}")
    at.close()
    print("\nM0 acceptance: PASS ✅")


if __name__ == "__main__":
    main()
