"""2026-11-15: big, public, vehicle and competitor leads never reach a gift."""

from __future__ import annotations

import json

import pytest

from system_b.clients import inventory as inv


@pytest.fixture
def data(tmp_path, monkeypatch):
    (tmp_path / "public-companies.json").write_text(json.dumps(
        {"0": {"cik_str": 1, "ticker": "TTC", "title": "TORO CO"},
         "1": {"cik_str": 2, "ticker": "DBX", "title": "Dropbox, Inc."}}))
    (tmp_path / "never-gift.txt").write_text("# comment\nAcentra Health\nMcLane/Midwest\n")
    monkeypatch.setattr(inv, "_DATA", tmp_path)
    inv._public_names.cache_clear()
    inv._never_gift.cache_clear()
    yield
    inv._public_names.cache_clear()
    inv._never_gift.cache_clear()


def test_norm_company():
    assert inv.norm_company("The Toro Company") == "toro"
    assert inv.norm_company("DROPBOX, INC.") == "dropbox"
    assert inv.norm_company("Gunster Yoakley & Stewart, P.A.") == "gunster yoakley and stewart"


@pytest.mark.parametrize("name,why", [
    ("The Toro Company", "public_company"),
    ("Dropbox, Inc.", "public_company"),
    ("255078, LLC", "not_a_company"),
    ("820 Chestnut LLC", "not_a_company"),
    ("Wheeler 2023 LLC", "not_a_company"),
    ("Constellation SPV LLC", "holding_or_hotel"),
    ("Hozho Springs Fund", "holding_or_hotel"),
    ("VF Registered Agent LLC", "registered_agent"),
    ("Firley, Moran, Freer & Eassa, CPA", "competitor"),
    ("Old World Painting LLC", None),
    ("Big Sky Construction Group", None),
])
def test_small_business_reason(data, name, why):
    assert inv.small_business_reason(name) == why


def test_never_gift_list(data):
    assert "acentra health" in inv._never_gift()
    assert "mclane midwest" in inv._never_gift()
    assert "comment" not in inv._never_gift()


def test_missing_files_filter_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(inv, "_DATA", tmp_path)
    inv._public_names.cache_clear()
    inv._never_gift.cache_clear()
    assert inv.small_business_reason("The Toro Company") is None
    assert inv._never_gift() == frozenset()
    inv._public_names.cache_clear()
    inv._never_gift.cache_clear()


def test_prospects_skip_role_inboxes_and_one_letter_names():
    from system_b.prospects import row_from_apollo
    base = {"Website": "acme.com", "Company Name": "Acme CPA", "Last Name": "Haubert"}
    assert row_from_apollo({**base, "Email": "tax@acme.com", "First Name": "Ann"}) is None
    assert row_from_apollo({**base, "Email": "ann@acme.com", "First Name": "Ann"})["first_name"] == "Ann"
    assert row_from_apollo({**base, "Email": "michale@acme.com", "First Name": "J"})["first_name"] == "Michale"
    assert row_from_apollo({**base, "Email": "jhaubert@acme.com", "First Name": "J"}) is None
