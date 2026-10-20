"""The lead inventory's published files (Inventory/exports/magnets): load,
identity, taxonomy. All offline, on files written to a temp dir."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from system_b.clients.inventory import (
    MAGNET_INDUSTRY,
    MAGNETS,
    StaleInventoryError,
    _entity_id,
    adapt_leadgen_lead,
    snapshot_all_magnets,
)
from system_b.gift.engine import _same_company, compute_match_level
from system_b.gift.models import Prospect
from system_b.gift.taxonomy import map_prospect
from system_b.clients.inventory import load_taxonomy

TODAY = date(2026, 10, 18)


def row(signal_type="federal_cost_reimbursement_contract", payload=None, *, name="Vantage Llc",
        industry="government_contracting", domain=None, expires="2026-12-16",
        event="2026-07-14", rid=None):
    return {
        "id": rid or f"uei:{(payload or {}).get('uei', 'X')}", "name": name, "domain": domain,
        "signal_type": signal_type, "industry": industry, "niche": None,
        "insight": f"{name} insight.", "city": "Lanham", "state": "MD", "score": 87,
        "as_of": "2026-10-17", "expires_at": expires, "status": "active",
        "signals": [{"type": signal_type, "event_date": f"{event}T00:00:00",
                     "date_confidence": "high", "evidence_text": "record",
                     "source_url": "https://www.usaspending.gov/award/X/",
                     "payload": dict(payload or {})}],
    }


def test_the_inventory_magnets_are_the_five_published_files():
    assert MAGNETS == {
        "nonprofit": "nonprofit-leads.json", "construction": "construction-leads.json",
        "govcon": "govcon-leads.json", "grant": "grant-leads.json",
        "newbusiness": "new-business-leads.json",
    }
    assert set(MAGNET_INDUSTRY) == set(MAGNETS)
    assert MAGNET_INDUSTRY["govcon"] == "government_contracting"
    assert MAGNET_INDUSTRY["grant"] is None        # untagged businesses stay generalist


@pytest.mark.parametrize("key,value,want", [
    ("uei", "RFCKU47QJQK3", "uei:RFCKU47QJQK3"),
    ("fl_license", "CGC1542099", "fl_license:CGC1542099"),
    ("wa_license", "ALLSECC741PN", "wa_license:ALLSECC741PN"),
    ("state_id", "CO:20261234567", "state_id:CO:20261234567"),
])
def test_a_government_id_makes_a_lead_findable_without_a_website(key, value, want):
    lead = adapt_leadgen_lead(row(payload={key: value}), today=TODAY)
    assert lead.domain is None
    assert lead.entity_id == want and lead.is_findable


def test_ids_rank_ein_first_and_one_ein_has_one_spelling():
    both = row(payload={"uei": "U1", "ein": "411386089"})
    assert _entity_id(both) == "ein:41-1386089"
    assert _entity_id(row(payload={"ein": "41-1386089"})) == "ein:41-1386089"


def test_two_files_naming_one_company_dedupe_on_the_shared_id():
    award = adapt_leadgen_lead(row("construction_federal_award_davis_bacon", {"uei": "U9"},
                                   name="Acme Builders Inc", industry="construction"),
                               today=TODAY)
    contract = adapt_leadgen_lead(row(payload={"uei": "U9"}, name="ACME BUILDERS"),
                                  today=TODAY)
    assert _same_company(contract, [award])
    other = adapt_leadgen_lead(row(payload={"uei": "U10"}, name="Other Co"), today=TODAY)
    assert not _same_company(other, [award])


def test_a_govcon_prospect_matches_govcon_leads_at_the_industry_level():
    tax = load_taxonomy()
    assert "government_contracting" in tax
    for phrase in ("government contractors", "federal contractors", "govcon firms"):
        assert map_prospect(phrase, tax) == ("niched", ("industry", "government_contracting"))
    lead = adapt_leadgen_lead(row(payload={"uei": "U1"}), today=TODAY)
    p = Prospect(firm_name="Ledger CFO", city="Lanham", state="MD", classification="niched",
                 match_param=("industry", "government_contracting"))
    assert compute_match_level(lead, p) == 1


def _publish(tmp_path, monkeypatch, name, rows, age_days):
    gen = (TODAY - timedelta(days=age_days)).isoformat()
    (tmp_path / name).write_text(json.dumps({"generated_at": f"{gen}T00:22:24",
                                             "contract": 2, "niche": "x",
                                             "count": len(rows), "leads": rows}))
    monkeypatch.setenv("LEADGEN_INVENTORY_DIR", str(tmp_path))


def test_a_30_day_old_published_file_loads(tmp_path, monkeypatch):
    _publish(tmp_path, monkeypatch, "govcon-leads.json",
             [row(payload={"uei": "U1"}), row(payload={"uei": "U2"}, name="Two Llc")], 30)
    snap = snapshot_all_magnets(today=TODAY)
    assert {ld.company for ld in snap.leads(industry="government_contracting")} == \
        {"Vantage LLC", "Two LLC"}


def test_a_file_past_45_days_stops_the_run(tmp_path, monkeypatch):
    _publish(tmp_path, monkeypatch, "grant-leads.json",
             [row("federal_first_time_grant", {"uei": "U1"}, industry=None)], 46)
    with pytest.raises(StaleInventoryError):
        snapshot_all_magnets(today=TODAY)


def test_the_new_families_age_by_their_own_expiry_only(tmp_path, monkeypatch):
    """A 180-day award window: an award dated 170 days ago is still a lead (no
    job-post ceiling), and one past its own expires_at is dropped at load."""
    old_event = (TODAY - timedelta(days=170)).isoformat()
    rows = [
        row("construction_federal_award_davis_bacon", {"uei": "U1"}, name="Kept Llc",
            industry="construction", event=old_event),
        row("construction_new_licensed_business", {"wa_license": "L1"}, name="Lapsed Llc",
            industry="construction", expires=(TODAY - timedelta(days=1)).isoformat(),
            rid="wa:L1"),
    ]
    _publish(tmp_path, monkeypatch, "construction-leads.json", rows, 1)
    nb = [row("new_business_formed", {"state_id": "CO:1"}, name="Fresh Llc", industry="other",
              event=old_event, rid="co:1")]
    (tmp_path / "new-business-leads.json").write_text(json.dumps(
        {"generated_at": TODAY.isoformat(), "contract": 2, "count": 1, "leads": nb}))
    names = {ld.company for ld in snapshot_all_magnets(today=TODAY).leads()}
    assert names == {"Kept LLC", "Fresh LLC"}
