"""Glue between the HTTP routes and the system_b library (Track H).

CSV ingest reuses the exact Step-0 rules from m4_walkthrough (website required,
headcount <= 10, domain de-dup) but adds CROSS-UPLOAD de-dup: a domain already
in Airtable is skipped, so re-uploading an Apollo export never double-adds. Rows
are tagged with their NichePack and land in the pending queue.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any
from urllib.parse import urlparse

_QUEUE_STATUS = {
    "researched": "pending",
    "email_1_queued": "pending",
    "email_1_sent": "in_sequence",
    "email_2_sent": "in_sequence",
    "email_3_sent": "in_sequence",
    "replied": "completed",
    "call_booked": "completed",
    "closed": "completed",
    "do_not_contact": "do_not_contact",
}


def domain_of(website: str) -> str:
    net = urlparse(website if "//" in website else f"//{website}").netloc.lower()
    return net[4:] if net.startswith("www.") else net


def _rows_from_csv(data: bytes) -> list[dict[str, Any]]:
    """Map Apollo CSV bytes to prospect dicts (mirrors m4.parse_csv_rows)."""
    out: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    for r in reader:
        hc_raw = (r.get("# Employees") or "").strip()
        try:
            headcount = int(hc_raw) if hc_raw else None
        except ValueError:
            headcount = None
        out.append({
            "firm_name": (r.get("Company Name for Emails") or r.get("Company Name") or "").strip(),
            "website": (r.get("Website") or "").strip(),
            "city": (r.get("City") or r.get("Company City") or "").strip(),
            "state": (r.get("State") or r.get("Company State") or "").strip(),
            "first_name": (r.get("First Name") or "").strip(),
            "email": (r.get("Email") or "").strip(),
            "linkedin": (r.get("Person Linkedin Url") or "").strip(),
            "headcount": headcount,
        })
    return out


def _existing_domains(at: Any) -> set[str]:
    out: set[str] = set()
    for rec in at.table.all(max_records=5000):
        w = rec["fields"].get("website")
        if w:
            out.add(domain_of(w))
    return out


def ingest_csv(at: Any, data: bytes, niche_pack: str) -> dict[str, Any]:
    """Create pending prospect rows from an Apollo CSV. Returns per-row outcome."""
    seen = _existing_domains(at)
    created, skipped = [], []
    for p in _rows_from_csv(data):
        firm = p["firm_name"] or "(unnamed)"
        if not p["website"]:
            skipped.append({"firm": firm, "reason": "no website"}); continue
        if p["headcount"] is not None and p["headcount"] > 10:
            skipped.append({"firm": firm, "reason": f"headcount {p['headcount']} > 10"}); continue
        dom = domain_of(p["website"])
        if dom and dom in seen:
            skipped.append({"firm": firm, "reason": f"duplicate domain {dom}"}); continue
        if dom:
            seen.add(dom)
        fields = {"firm_name": p["firm_name"], "website": p["website"], "stage": "researched",
                  "niche_pack": niche_pack}
        for k in ("city", "state", "first_name", "email", "linkedin"):
            if p.get(k):
                fields[k] = p[k]
        rec = at.create_prospect(fields)
        created.append({"record_id": rec["id"], "firm": firm})
    return {"niche_pack": niche_pack, "created": len(created), "skipped": len(skipped),
            "created_rows": created, "skipped_rows": skipped}


def queue(at: Any) -> list[dict[str, Any]]:
    """The prospect queue (H1) with a derived pending/in_sequence/completed status."""
    out = []
    for rec in at.table.all(max_records=5000):
        f = rec["fields"]
        stage = f.get("stage") or "researched"
        out.append({
            "record_id": rec["id"],
            "firm_name": f.get("firm_name"),
            "domain": domain_of(f["website"]) if f.get("website") else None,
            "niche_pack": f.get("niche_pack") or "cfo",
            "city": f.get("city"), "state": f.get("state"),
            "stage": stage,
            "status": _QUEUE_STATUS.get(stage, "pending"),
            "review_status": f.get("review_status") or "",
            "frozen": bool(f.get("frozen")),
            "eligible_for_send": bool(f.get("eligible_for_send")),
        })
    return out


def _parse(raw: Any) -> dict[str, Any] | None:
    try:
        return json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None


def pending_cards(at: Any, channel: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """Structured cards awaiting review (H3), across BOTH channels. A prospect can
    have an email card (card_json) AND a LinkedIn card (li_card_json) pending at
    once — each appears separately with a unique card_id. Returns (filtered, total).
    `total` ignores the channel filter so the UI can show a per-channel walk plus
    an overall count."""
    cards, total = [], 0
    for rec in at.table.all(max_records=5000):
        f = rec["fields"]
        if f.get("frozen"):
            continue
        eligible = bool(f.get("eligible_for_send"))
        # email card
        if (f.get("review_status") or "") in ("pending", "edited"):
            p = _parse(f.get("card_json"))
            if p:
                total += 1
                if not channel or p.get("channel", "email") == channel:
                    p.update({"record_id": rec["id"], "card_id": f"{rec['id']}:email",
                              "review_status": f.get("review_status"), "eligible_for_send": eligible})
                    cards.append(p)
        # LinkedIn card
        if (f.get("li_review_status") or "") in ("pending", "edited"):
            p = _parse(f.get("li_card_json"))
            if p:
                total += 1
                if not channel or p.get("channel") == channel:
                    p.update({"record_id": rec["id"], "card_id": f"{rec['id']}:linkedin",
                              "review_status": f.get("li_review_status"), "eligible_for_send": eligible})
                    cards.append(p)
    cards.sort(key=lambda c: (c.get("channel", "email"),
                              str(c.get("step", 1)),
                              c.get("prospect", {}).get("firm_name") or ""))
    return cards, total


def linkedin_queue(at: Any) -> list[dict[str, Any]]:
    """LinkedIn work-by-hand queue (H4/F): pending connection requests to send,
    and approved DMs to paste. connection_accepted gates the next DM."""
    out = []
    for rec in at.table.all(max_records=5000):
        f = rec["fields"]
        if f.get("frozen"):
            continue
        base = {
            "record_id": rec["id"],
            "firm_name": f.get("firm_name"),
            "linkedin": f.get("linkedin"),
            "connection_accepted": bool(f.get("connection_accepted")),
        }
        if f.get("li_connect_pending"):
            out.append({**base, "kind": "connect", "message": None})
        if f.get("li_review_status") == "approved" and f.get("li_message"):
            out.append({**base, "kind": f.get("li_step") or "dm",
                        "message": {"body": f.get("li_message")}})
    return out
