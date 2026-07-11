"""Trucking niche pack: inventory adapter, geo-matched gift, and honest copy.

The CFO path is unchanged (its suite still passes); these cover the new pack
end-to-end from an insurance-pipeline trucking row to a rendered email.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.trucking import (
    TRUCKING_PACK,
    adapt_trucking_lead,
    load_trucking_leads,
    trucking_descriptions,
    trucking_snapshot,
)

TODAY = date(2026, 7, 11)


def _row(name: str, state: str, city: str, usdot: str, issue: str, power: int = 3) -> dict:
    return {
        "name": name,
        "domain": f"{name.split()[0].lower()}.com",
        "industry": "logistics_transport",
        "city": city,
        "state": state,
        "insight": f"{name} just registered with the fmcsa",
        "signals": [
            {
                "type": "new_motor_carrier_authority",
                "captured_at": f"{issue}T00:00:00",
                "days_ago": 5,
                "payload": {
                    "usdot": usdot,
                    "city": city,
                    "state": state,
                    "issue_date": issue,
                    "fleet_size_power_units": power,
                },
            }
        ],
    }


def _write_inventory(tmp_path: Path, rows: list[dict]) -> str:
    p = tmp_path / "trucking-leads.json"
    p.write_text(json.dumps({"generated_at": "2026-07-11T00:00:00", "leads": rows}))
    return str(p)


# --- adapter ---------------------------------------------------------------

def test_adapter_maps_fields() -> None:
    lead = adapt_trucking_lead(_row("Alpha Trucking LLC", "TX", "Dallas", "111", "2026-07-01"), today=TODAY)
    assert lead.id == "usdot:111"
    assert lead.company == "Alpha Trucking LLC"
    assert lead.state == "TX" and lead.city == "Dallas"
    assert lead.signal_type == "new_motor_carrier_authority"
    assert lead.freshness == "fresh"                    # issued 10 days ago
    assert "operating authority" in lead.signals[0].plain_words_description


def test_adapter_freshness_decays() -> None:
    old = adapt_trucking_lead(_row("Old Freight Inc", "TX", "Waco", "222", "2026-05-01"), today=TODAY)
    assert old.freshness == "stale"                     # > 30 days


def test_adapter_synthesizes_id_without_usdot() -> None:
    row = _row("No Dot Carrier", "TX", "Austin", "", "2026-07-05")
    row["signals"][0]["payload"]["usdot"] = None
    lead = adapt_trucking_lead(row, today=TODAY)
    assert lead.id.startswith("trucking:")


def test_load_from_file(tmp_path: Path) -> None:
    path = _write_inventory(tmp_path, [_row("Alpha Trucking LLC", "TX", "Dallas", "111", "2026-07-01")])
    leads = load_trucking_leads(path, today=TODAY)
    assert len(leads) == 1 and leads[0].company == "Alpha Trucking LLC"


# --- gift (geo match) ------------------------------------------------------

def test_gift_matches_carriers_in_agents_state(tmp_path: Path) -> None:
    path = _write_inventory(tmp_path, [
        _row("Alpha Trucking LLC", "TX", "Dallas", "111", "2026-07-01"),
        _row("Beta Freight Inc", "TX", "Houston", "112", "2026-07-02"),
        _row("Gamma Haul Co", "CA", "Fresno", "113", "2026-07-03"),   # out of state
    ])
    snap = trucking_snapshot(path, today=TODAY)
    agent = Prospect(firm_name="Lone Star Insurance", state="TX", classification="generalist", first_name="sam")
    gift = build_gift(agent, snap, pack=TRUCKING_PACK)
    assert gift is not None
    states = {l.state for l in gift.leads}
    assert states == {"TX"}                              # never the CA carrier
    assert gift.geo_level == "state"


def test_no_gift_when_no_carriers_in_state(tmp_path: Path) -> None:
    path = _write_inventory(tmp_path, [_row("Gamma Haul Co", "CA", "Fresno", "113", "2026-07-03")])
    snap = trucking_snapshot(path, today=TODAY)
    agent = Prospect(firm_name="Empire Trucking Ins", state="NY", classification="generalist")
    assert build_gift(agent, snap, pack=TRUCKING_PACK) is None


# --- copy (honesty) --------------------------------------------------------

def test_email_is_honest_and_trucking_voiced(tmp_path: Path) -> None:
    path = _write_inventory(tmp_path, [
        _row("Alpha Trucking LLC", "TX", "Dallas", "111", "2026-07-01"),
        _row("Beta Freight Inc", "TX", "Houston", "112", "2026-07-02"),
    ])
    snap = trucking_snapshot(path, today=TODAY)
    agent = Prospect(firm_name="Lone Star Insurance", state="TX", classification="generalist", first_name="sam")
    gift = build_gift(agent, snap, pack=TRUCKING_PACK)
    descriptions = trucking_descriptions(gift.leads)
    draft = build_email_1(gift, agent, descriptions, today=TODAY, pack=TRUCKING_PACK)

    assert draft.subject == "new carriers in texas that just got their authority"
    assert "$" not in draft.body
    assert "new texas carriers that just got their authority" in draft.body
    assert "hey sam," in draft.body
    # company names keep their casing; surrounding prose is lowercase.
    assert "Alpha Trucking LLC" in draft.body
    assert "fractional cfo" not in draft.body            # no CFO voice leaked in
