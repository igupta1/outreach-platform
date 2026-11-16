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
    _source     -> _source        (the Apollo list(s) it came from)
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


_ROLE_INBOXES = frozenset({
    "info", "office", "admin", "contact", "contactus", "hello", "support", "team", "tax",
    "taxes", "accounting", "bookkeeping", "books", "mail", "inquiries", "inquiry",
    "enquiries", "sales", "service", "services", "help", "billing", "frontdesk",
    "reception", "general", "cpa", "staff", "clients", "client", "payroll", "finance",
    # 2026-11-15 review of the 1,200 batch
    "marketing", "clarity", "grow", "growth", "cfo", "bookkeeper", "accounts", "ar", "ap",
    "hr", "careers", "jobs", "media", "press", "partners", "connect", "welcome", "start",
})
_NICKNAMES = {
    "michael": {"mike"}, "robert": {"bob", "rob", "bobby"}, "william": {"bill", "will"},
    "lawrence": {"larry"}, "laurence": {"larry"}, "jessica": {"jessie", "jess"},
    "gabriel": {"gabe"}, "andrew": {"andy", "drew"}, "david": {"dave"},
    "stephen": {"steve"}, "steven": {"steve"}, "thomas": {"tom"}, "james": {"jim", "jamie"},
    "aleksandr": {"alex"}, "alexander": {"alex"}, "rachel": {"rae"}, "alfredo": {"alfred"},
    "richard": {"rick", "rich"}, "joseph": {"joe"}, "daniel": {"dan", "danny"},
    "christopher": {"chris"}, "matthew": {"matt"}, "nicholas": {"nick"},
    "jennifer": {"jen", "jenn"}, "katherine": {"kate", "katie"}, "kathryn": {"kate", "katie"},
    "elizabeth": {"liz", "beth"}, "patricia": {"pat", "patty"}, "samuel": {"sam"},
    "benjamin": {"ben"}, "anthony": {"tony"}, "edward": {"ed", "eddie"}, "timothy": {"tim"},
    "gregory": {"greg"}, "jonathan": {"jon"}, "kenneth": {"ken"}, "ronald": {"ron"},
    "donald": {"don"}, "charles": {"chuck", "charlie"}, "jeffrey": {"jeff"},
    "zachary": {"zach"}, "douglas": {"doug"}, "frederick": {"fred"}, "victoria": {"vicki"},
}
# A numbered role box ("lead2@", "sales1@").
_ROLE_NUMBERED_RE = re.compile(r"^(?:lead|sales|info|office|team|admin|support)\d+$")


def row_from_apollo(record: dict[str, str]) -> dict[str, Any] | None:
    """Map one Apollo CSV record to the generator's row dict, or None if it has
    no website (nothing to research) or no email (nothing to export)."""
    website = _normalize_website(record.get("Website", ""))
    email = _clean(record.get("Email"))
    if not website or not email:
        return None
    # No shared inboxes (tax@, info@): the user's rule, and nobody reads them
    # as a person (2026-11-15: two tax@ inboxes reached a batch).
    local = email.split("@", 1)[0].lower()
    if local in _ROLE_INBOXES or _ROLE_NUMBERED_RE.match(local):
        return None
    first = _clean(record.get("First Name")) or None
    # Stray punctuation ("Jeorgia'", 2026-11-15).
    if first:
        first = first.strip(" '\".,;:-`") or None
    # The name the person signs with, when the address shows it: "mike@" for
    # Michael, "larry@" for Lawrence (2026-11-15).
    if first and local in _NICKNAMES.get(first.lower(), ()):
        first = local.capitalize()
    # A first name that is one letter ("J", "P") would open "hey j,"
    # (2026-11-15). The address's own name stands in when it is a plain word
    # that is not the surname ("michale@" for J. Michale Haubert); otherwise
    # the contact is skipped.
    if first and len(first.replace(".", "")) <= 1:
        last = (_clean(record.get("Last Name")) or "").lower()
        if local.isalpha() and len(local) >= 3 and last and last not in local:
            first = local.capitalize()
        else:
            return None
    company = _clean(record.get("Company Name")) or _clean(
        record.get("Company Name for Emails")
    )
    return {
        "firm_name": company,
        "website": website,
        # Apollo ships BOTH a person-level City/State and a company-level
        # "Company City"/"Company State", and which one is populated depends on
        # the export. The company's location is the one copy claims ("companies
        # in denver"), so it wins; the person's is the fallback.
        "city": (_clean(record.get("Company City"))
                 or _clean(record.get("City")) or None),
        "state": (_clean(record.get("Company State"))
                  or _clean(record.get("State")) or None),
        "first_name": first,
        # Carried for ONE reason: a LinkedIn reply weeks later shows a full
        # name, and "Paul" + a company column is a bad key to search a
        # thousand-row history by. Never rendered into copy.
        "last_name": _clean(record.get("Last Name")) or None,
        # Only to tell a CPA ("Partner, CPA"): CPA-only leads go to CPAs
        # (gift.engine.CPA_ONLY_TAGS). Never rendered into copy.
        "title": _clean(record.get("Title")) or None,
        "email": email,
        "linkedin": _clean(record.get("Person Linkedin Url")),
        # Which Apollo finance-firm list(s) the contact came from, joined with
        # "+" ("FractionalCFO+Accounting"). Picks the voice when their site
        # never says which service they sell (sequence/generate.choose_voice).
        "_source": _clean(record.get("_source")),
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
