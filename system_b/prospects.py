"""Read an Apollo contact export into the flat prospect `row` the generator
expects. No network, no state — just column mapping + light cleaning.

Apollo's export is wide (60+ columns); we use only what a sequence needs:

    First Name  -> first_name
    Last Name   -> last_name      (only for finding the row again later)
    Company Name-> firm_name / company
    Email       -> email
    Website     -> website        (required; rows without one are skipped)
    City        -> city
    State       -> state
    Person Linkedin Url -> linkedin
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

# Apollo header -> our row key. Company falls back to "Company Name for Emails".
_SCHEME = "https://"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _normalize_website(raw: str) -> str:
    """Bare domains ('acme.com') get an https:// scheme so the fetcher can GET
    them; anything already schemed is left alone. Blank stays blank."""
    url = _clean(raw)
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = _SCHEME + url
    return url


def row_from_apollo(record: dict[str, str]) -> dict[str, Any] | None:
    """Map one Apollo CSV record to the generator's row dict, or None if it has
    no website (nothing to research) or no email (nothing to export)."""
    website = _normalize_website(record.get("Website", ""))
    email = _clean(record.get("Email"))
    if not website or not email:
        return None
    company = _clean(record.get("Company Name")) or _clean(
        record.get("Company Name for Emails")
    )
    return {
        "firm_name": company,
        "website": website,
        "city": _clean(record.get("City")) or None,
        "state": _clean(record.get("State")) or None,
        "first_name": _clean(record.get("First Name")) or None,
        # Carried for ONE reason: a LinkedIn reply weeks later shows a full
        # name, and "Paul" + a company column is a bad key to search a
        # thousand-row history by. Never rendered into copy.
        "last_name": _clean(record.get("Last Name")) or None,
        "email": email,
        "linkedin": _clean(record.get("Person Linkedin Url")),
    }


def read_apollo_csv(path: str | Path) -> list[dict[str, Any]]:
    """Every usable prospect row from an Apollo export, in file order.
    Rows without a website or email are dropped."""
    rows: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for record in csv.DictReader(fh):
            row = row_from_apollo(record)
            if row:
                rows.append(row)
    return rows
