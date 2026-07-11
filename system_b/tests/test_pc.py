"""Commercial P&C pack + insurance-agency router: adapter, geo gift, honesty
(no dollar amounts on a raise), and trucking-vs-P&C dispatch."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches import insurance_agency as router
from system_b.niches.pc import (
    PC_PACK,
    adapt_pc_lead,
    pc_descriptions,
    pc_snapshot,
)

TODAY = date(2026, 7, 11)


def _row(name, state, city, trigger, posted="2026-07-02", insight="just raised a seed round of $2M"):
    return {
        "name": name, "domain": f"{name.split()[0].lower()}.com", "industry": "software_saas",
        "city": city, "state": state, "trigger_type": trigger, "insight": insight,
        "signals": [{"type": trigger, "captured_at": f"{posted}T00:00:00", "days_ago": 9, "payload": {}}],
    }


def _write(tmp_path: Path, rows: list[dict]) -> str:
    p = tmp_path / "pc-leads.json"
    p.write_text(json.dumps({"generated_at": "2026-07-11T00:00:00", "leads": rows}))
    return str(p)


def test_adapter_maps_trigger() -> None:
    lead = adapt_pc_lead(_row("Nimbus AI", "CA", "San Jose", "funding_raised"), today=TODAY)
    assert lead.signal_type == "funding_raised" and lead.freshness == "fresh"
    assert lead.signals[0].plain_words_description == "just raised"


def test_gift_matches_by_state(tmp_path: Path) -> None:
    path = _write(tmp_path, [
        _row("Nimbus AI", "CA", "San Jose", "funding_raised"),
        _row("Coast Foods", "CA", "Fresno", "new_business_filed"),
        _row("Empire Corp", "NY", "Albany", "funding_raised"),   # out of state
    ])
    snap = pc_snapshot(path, today=TODAY)
    agent = Prospect(firm_name="Golden State Commercial", state="CA", classification="generalist", first_name="ana")
    gift = build_gift(agent, snap, pack=PC_PACK)
    assert gift is not None
    assert {l.state for l in gift.leads} == {"CA"}


def test_email_never_shows_dollar_amount(tmp_path: Path) -> None:
    # The insight carries "$2M"; the P&C lead line must template the raise and
    # never leak a figure.
    path = _write(tmp_path, [
        _row("Nimbus AI", "CA", "San Jose", "funding_raised"),
        _row("Coast Foods", "CA", "Fresno", "new_business_filed"),
    ])
    snap = pc_snapshot(path, today=TODAY)
    agent = Prospect(firm_name="Golden State Commercial", state="CA", classification="generalist", first_name="ana")
    gift = build_gift(agent, snap, pack=PC_PACK)
    draft = build_email_1(gift, agent, pc_descriptions(gift.leads), today=TODAY, pack=PC_PACK)
    assert "$" not in draft.body and "2M" not in draft.body        # no figure leaks
    assert draft.subject == "companies in california whose coverage needs probably just changed"
    assert "just raised" in draft.body
    assert "just registered as a new business" in draft.body
    assert "fractional cfo" not in draft.body


# --- router ----------------------------------------------------------------

def test_classify_subniche() -> None:
    assert router.classify_subniche("we write trucking and motor carrier insurance") == "trucking"
    assert router.classify_subniche("commercial fleet and cargo coverage") == "trucking"
    assert router.classify_subniche("general liability and workers comp for smbs") == "pc"
    assert router.classify_subniche("") == "pc"                    # default


def test_route_returns_right_pack() -> None:
    pack_t, snap_t, desc_t = router.route("trucking")
    pack_p, snap_p, desc_p = router.route("pc")
    assert pack_t.key == "trucking" and pack_p.key == "pc"
    assert router.route("unknown")[0].key == "pc"                  # default
