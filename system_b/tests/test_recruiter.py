"""Recruiter niche pack: adapter, function match, geo fallback, honest copy."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.niches.recruiter import (
    RECRUITER_PACK,
    adapt_recruiter_lead,
    recruiter_descriptions,
    recruiter_prospect,
    recruiter_snapshot,
)

TODAY = date(2026, 7, 11)


def _row(name: str, state: str, city: str, func: str, count: int = 4, posted: str = "2026-07-02") -> dict:
    return {
        "name": name, "domain": None, "city": city, "state": state,
        "unique_role_count": count, "primary_function": func,
        "functions": {func: count}, "insight": f"hiring {count} roles right now, mostly {func}",
        "signals": [{"type": "hiring_volume", "captured_at": f"{posted}T00:00:00",
                     "payload": {"unique_role_count": count, "primary_function": func, "date": posted}}],
    }


def _write(tmp_path: Path, rows: list[dict]) -> str:
    p = tmp_path / "recruiter-leads.json"
    p.write_text(json.dumps({"generated_at": "2026-07-11T00:00:00", "leads": rows}))
    return str(p)


def test_adapter_maps_function_to_niche() -> None:
    lead = adapt_recruiter_lead(_row("Acme Corp", "TX", "Austin", "finance", count=5), today=TODAY)
    assert lead.niche == "finance" and lead.industry == "finance"
    assert lead.signal_type == "hiring_volume" and lead.freshness == "fresh"
    assert lead.signals[0].plain_words_description == "posted 5 roles this month"


def test_niched_recruiter_matches_on_function(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        _row("Alpha Health", "TX", "Austin", "finance"),
        _row("Beta Labs", "TX", "Dallas", "finance"),
        _row("Delta Corp", "TX", "Waco", "finance"),      # 3 finance in TX -> no geo padding
        _row("Gamma Foods", "CA", "Fresno", "sales"),     # out of state + off-function
    ])
    snap = recruiter_snapshot(path, today=TODAY)
    fin = recruiter_prospect("FinHire Staffing", state="TX", function="finance", first_name="lee")
    gift = build_gift(fin, snap, pack=RECRUITER_PACK)
    assert gift is not None
    assert all(l.niche == "finance" for l in gift.leads)     # only finance hirers
    assert gift.all_niche is True
    draft = build_email_1(gift, fin, recruiter_descriptions(gift.leads), today=TODAY, pack=RECRUITER_PACK)
    assert draft.subject == "companies in texas hiring finance right now"
    assert "saw you recruit finance" in draft.body


def test_geo_fallback_drops_function_claim(tmp_path: Path) -> None:
    # A finance recruiter in NY, but the only NY hirer is a sales company: the
    # engine falls back to geo and the honesty gate must drop "finance".
    path = _write(tmp_path, [
        _row("Empire Foods", "NY", "Buffalo", "sales"),
        _row("Hudson Retail", "NY", "Albany", "sales"),    # 2 -> plural, both off-function
    ])
    snap = recruiter_snapshot(path, today=TODAY)
    fin = recruiter_prospect("Gotham Finance Recruiters", state="NY", function="finance", first_name="sam")
    gift = build_gift(fin, snap, pack=RECRUITER_PACK)
    assert gift is not None
    assert gift.all_niche is False                            # matched on geo, not function
    draft = build_email_1(gift, fin, recruiter_descriptions(gift.leads), today=TODAY, pack=RECRUITER_PACK)
    assert "finance" not in draft.subject                     # no false function claim
    assert draft.subject == "companies in new york hiring heavily right now"


def test_generalist_recruiter_matches_on_geo(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        _row("Alpha Health", "TX", "Austin", "finance"),
        _row("Gamma Foods", "CA", "Fresno", "sales"),          # out of state
    ])
    snap = recruiter_snapshot(path, today=TODAY)
    gen = recruiter_prospect("Lone Star Staffing", state="TX", first_name="dana")
    gift = build_gift(gen, snap, pack=RECRUITER_PACK)
    assert gift is not None
    assert {l.state for l in gift.leads} == {"TX"}


def test_email_is_honest(tmp_path: Path) -> None:
    path = _write(tmp_path, [_row("Alpha Health", "TX", "Austin", "finance")])
    snap = recruiter_snapshot(path, today=TODAY)
    fin = recruiter_prospect("FinHire Staffing", state="TX", function="finance", first_name="lee")
    gift = build_gift(fin, snap, pack=RECRUITER_PACK)
    draft = build_email_1(gift, fin, recruiter_descriptions(gift.leads), today=TODAY, pack=RECRUITER_PACK)
    assert "$" not in draft.body
    assert "hey lee," in draft.body
    assert "fractional cfo" not in draft.body
    assert "Alpha Health" in draft.body
