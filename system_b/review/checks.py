"""The batch checks Claude ran by hand on every 200-email batch, in code.

    system_b/.venv/bin/python -m system_b.review.checks --review sequences.review.json

The nightly job (`system_b.nightly`) runs these on the finished batch and
stores them in the review JSON under `checks`; the review page lists them at
the top, so the morning starts from "fix these" rather than from reading 200
cards. Each is something that reached a review in October / November 2026:

  * a greeting with no first name ("hey there,");
  * an em dash anywhere in the copy (house style: none);
  * a registry name the tidier left alone: a trailing ", The", a missing
    apostrophe ("Childrens"), a legal form in a lead line ("P.A.", "Corp");
  * a name fix the guard refused (the card's own note);
  * a subject past SUBJECT_MAX characters (it truncates on a phone);
  * a location-only email that opens on the firm's client revenue
    ("saw you work with $100m+ companies. here are 3 nonprofits...");
  * a gift smaller than three;
  * a client-list niche (presence-only: confirm they are clients).

`fix` items are worth an edit before sending; `look` items are worth a glance.
Nothing here edits a card.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SUBJECT_MAX = 50

_APOSTROPHE_RE = re.compile(r"\b(Childrens|Mens|Womens|Veterans Of|Peoples)\b")
_TRAILING_THE_RE = re.compile(r",\s*The\b")
_LEGAL_RE = re.compile(r"(?:,\s*|\s)(?:P\.?\s?A\.?|P\.?\s?C\.?|S\.?\s?C\.?|L\.?L\.?C\.?|Inc\.?|Corp\.?|"
                       r"Ltd\.?|LLLP|PLLC)(?=[,:\s]|$)")
_LEAD_LINE_RE = re.compile(r"^\s*\d+\.\s+(.+)$", re.M)


def _item(kind: str, card: dict[str, Any], what: str) -> dict[str, str]:
    return {"kind": kind, "company": card.get("company") or "", "email": card.get("email") or "",
            "what": what}


def _lead_names(head: str) -> list[str]:
    out = []
    for line in _LEAD_LINE_RE.findall(head or ""):
        out.append(re.split(r":\s|, [a-z]", line, maxsplit=1)[0].strip())
    return out


def check_card(card: dict[str, Any], row: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Every item for one prospect. `row` is its CSV row (the email as it will
    be sent); without one the card's own copy is read."""
    row = row or {}
    head = card.get("email_1_head") or row.get("email_1") or ""
    body = "\n".join(filter(None, [row.get("email_1") or head, row.get("email_2") or card.get("email_2"),
                                   row.get("email_3") or card.get("email_3")]))
    subject = row.get("subject") or card.get("subject") or ""
    items: list[dict[str, str]] = []

    first = (row.get("first_name") or card.get("first_name") or "").strip()
    if not first or head.lower().startswith("hey there"):
        items.append(_item("fix", card, "no first name: the email opens \"hey there,\""))
    elif not head.lower().startswith("hey "):
        items.append(_item("fix", card, "no greeting"))
    if "—" in body:
        items.append(_item("fix", card, "em dash in the copy"))
    if _TRAILING_THE_RE.search(head):
        items.append(_item("fix", card, "a name ends in \", The\": move The to the front"))
    for m in _APOSTROPHE_RE.findall(head):
        items.append(_item("fix", card, f"missing apostrophe: \"{m}\""))
    for name in _lead_names(head):
        if _LEGAL_RE.search(name):
            items.append(_item("look", card, f"legal form left in a lead name: \"{name}\""))
    if len(subject) > SUBJECT_MAX:
        items.append(_item("look", card, f"subject is {len(subject)} characters: \"{subject}\""))
    if not card.get("niche") and re.search(r"saw you work with \$", head):
        items.append(_item("fix", card, "location-only email opens on client revenue; the leads "
                                        "are not in their industry, so cut that sentence"))
    if (card.get("gift_size") or len(card.get("leads") or []) or 3) < 3:
        items.append(_item("look", card, "fewer than 3 leads in the gift"))
    for flag in card.get("flags") or []:
        if flag.startswith("name kept as the registry wrote it"):
            items.append(_item("look", card, flag))
        elif flag.startswith("client-list niche is presence-only"):
            items.append(_item("look", card, "industry read from a client list: confirm they are clients"))
    return items


def check_batch(review: dict[str, Any], rows: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """{"items": [...], "summary": {...}} for the whole batch."""
    by_email = {(r.get("email") or "").strip().lower(): r for r in rows or []}
    cards = review.get("prospects") or []
    items: list[dict[str, str]] = []
    for card in cards:
        items += check_card(card, by_email.get((card.get("email") or "").strip().lower()))
    kinds = Counter(i["kind"] for i in items)
    niche = sum(1 for c in cards if c.get("niche"))
    return {
        "items": items,
        "summary": {
            "prospects": len(cards),
            "industry_match": niche,
            "location_only": len(cards) - niche,
            "no_gift": len(review.get("skipped") or []),
            "fix": kinds.get("fix", 0),
            "look": kinds.get("look", 0),
        },
    }


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--review", default="sequences.review.json")
    ap.add_argument("--csv", default=None, help="the batch CSV (default: beside the review)")
    ap.add_argument("--write", action="store_true", help="store the result in the review JSON")
    a = ap.parse_args(argv)
    review_path = Path(a.review)
    review = json.loads(review_path.read_text())
    csv_path = Path(a.csv) if a.csv else review_path.with_name(
        review_path.name.replace(".review.json", ".csv"))
    result = check_batch(review, read_rows(csv_path))
    s = result["summary"]
    print(f"{s['prospects']} prospects · {s['industry_match']} industry match · "
          f"{s['location_only']} location only · {s['fix']} to fix · {s['look']} to look at")
    for i in result["items"]:
        print(f"  [{i['kind']}] {i['company']}: {i['what']}")
    if a.write:
        review["checks"] = result
        review_path.write_text(json.dumps(review, indent=1, default=str))


if __name__ == "__main__":
    main()
