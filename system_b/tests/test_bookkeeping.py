"""Bookkeeping niche pack: adapter, geo-matched gift, honest copy. CFO path
unchanged; these cover the pack end-to-end from a cfo-pipeline bookkeeping row."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.bookkeeping import (
    BOOKKEEPING_PACK,
    adapt_bookkeeping_lead,
    bookkeeping_descriptions,
    bookkeeping_snapshot,
    load_bookkeeping_leads,
)

TODAY = date(2026, 7, 11)


def _row(name: str, state: str, city: str, title: str, posted: str) -> dict:
    return {
        "name": name,
        "domain": f"{name.split()[0].lower()}.com",
        "city": city,
        "state": state,
        "industry": None,
        "role_tier": "junior",
        "insight": f"hiring a {title.lower()}",
        "signals": [
            {
                "type": "job_posted_bookkeeping",
                "captured_at": f"{posted}T00:00:00",
                "payload": {
                    "title": title,
                    "role_tier": "junior",
                    "date_posted": posted,
                    "city": city,
                    "state": state,
                },
            }
        ],
    }


def _write(tmp_path: Path, rows: list[dict]) -> str:
    p = tmp_path / "bookkeeping-leads.json"
    p.write_text(json.dumps({"generated_at": "2026-07-11T00:00:00", "leads": rows}))
    return str(p)


def test_adapter_maps_fields() -> None:
    lead = adapt_bookkeeping_lead(_row("Sunrise Dental", "TX", "Austin", "Bookkeeper", "2026-07-01"), today=TODAY)
    assert lead.company == "Sunrise Dental"
    assert lead.state == "TX" and lead.city == "Austin"
    assert lead.signal_type == "job_posted_bookkeeping"
    assert lead.freshness == "fresh"
    assert lead.signals[0].plain_words_description == "just posted a bookkeeper role"


def test_load_from_file(tmp_path: Path) -> None:
    path = _write(tmp_path, [_row("Sunrise Dental", "TX", "Austin", "Bookkeeper", "2026-07-01")])
    leads = load_bookkeeping_leads(path, today=TODAY)
    assert len(leads) == 1 and leads[0].company == "Sunrise Dental"


def test_gift_matches_companies_in_firms_state(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        _row("Sunrise Dental", "TX", "Austin", "Bookkeeper", "2026-07-01"),
        _row("Vista Clinic", "TX", "Houston", "Staff Accountant", "2026-07-02"),
        _row("Bay Cafe Group", "CA", "Oakland", "Payroll Specialist", "2026-07-03"),  # out of state
    ])
    snap = bookkeeping_snapshot(path, today=TODAY)
    firm = Prospect(firm_name="Hill Country Books", state="TX", classification="generalist", first_name="mia")
    gift = build_gift(firm, snap, pack=BOOKKEEPING_PACK)
    assert gift is not None
    assert {l.state for l in gift.leads} == {"TX"}
    assert gift.geo_level == "state"


def test_email_is_honest_and_bookkeeping_voiced(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        _row("Sunrise Dental", "TX", "Austin", "Bookkeeper", "2026-07-01"),
        _row("Vista Clinic", "TX", "Houston", "Staff Accountant", "2026-07-02"),
    ])
    snap = bookkeeping_snapshot(path, today=TODAY)
    firm = Prospect(firm_name="Hill Country Books", state="TX", classification="generalist", first_name="mia")
    gift = build_gift(firm, snap, pack=BOOKKEEPING_PACK)
    draft = build_email_1(gift, firm, bookkeeping_descriptions(gift.leads), today=TODAY, pack=BOOKKEEPING_PACK)

    assert draft.subject == "companies in texas hiring junior finance right now"
    assert "$" not in draft.body
    assert "could use bookkeeping help" in draft.body
    assert "hey mia," in draft.body
    assert "Sunrise Dental" in draft.body
    assert "fractional cfo" not in draft.body            # no CFO voice leaked in
