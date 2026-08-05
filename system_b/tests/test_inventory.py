"""Tests for the leadgen inventory adapter (clients/inventory.py).

Covers the single place that maps a `leadgen` per-niche inventory row onto the
outreach `Lead`, and the stub-mode `SnapshotScraper` it serves them through.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_inventory.py -q
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from system_b import config
from system_b.clients import inventory as inv
from system_b.clients.inventory import (
    VALID_NICHES,
    adapt_leadgen_lead,
    snapshot_for_niche,
)
from system_b.models import Lead

TODAY = date(2026, 7, 20)


def _row(**kw):
    """A representative leadgen inventory row. Override any field via kwargs."""
    base = {
        "id": "row-1",
        "name": "Acme Corp",
        "insight": "growing fast, could use finance help",
        "signal_type": "job_finance_lead",
        "niche": "cfo",
        "industry": "healthcare",
        "city": "Denver",
        "state": "CO",
        "domain": "acme.com",
        "signals": [
            {
                "type": "job_finance_lead",
                "event_date": "2026-07-01",
                "evidence_text": "posted a controller role",
            }
        ],
    }
    base.update(kw)
    return base


# --------------------------------------------------------------------------
# adapt_leadgen_lead — field mapping
# --------------------------------------------------------------------------

def test_adapt_maps_core_fields():
    lead = adapt_leadgen_lead(_row(), today=TODAY)
    assert isinstance(lead, Lead)
    assert lead.company == "Acme Corp"                       # company <- name
    assert lead.value_prop == "growing fast, could use finance help"  # value_prop <- insight
    assert lead.signal_type == "job_finance_lead"            # passthrough (verbatim leadgen type)
    assert lead.industry == "healthcare"                     # passthrough
    assert lead.city == "Denver"                             # passthrough
    assert lead.state == "CO"                                # passthrough
    assert lead.domain == "acme.com"                         # passthrough
    assert lead.id == "row-1"                                # uses row["id"] when present


def test_adapt_niche_passthrough_including_none():
    assert adapt_leadgen_lead(_row(niche="mssp"), today=TODAY).niche == "mssp"
    # niche <- row.get("niche"); a missing/None niche stays None (not defaulted)
    assert adapt_leadgen_lead(_row(niche=None), today=TODAY).niche is None
    no_niche = _row()
    del no_niche["niche"]
    assert adapt_leadgen_lead(no_niche, today=TODAY).niche is None


def test_adapt_signals_each_mapped_to_outreach_signal():
    row = _row(
        signals=[
            {"type": "job_finance_lead", "event_date": "2026-07-01", "evidence_text": "posted a controller role"},
            {"type": "funding_form_d", "event_date": "2026-06-15", "evidence_text": "filed a form d"},
        ]
    )
    lead = adapt_leadgen_lead(row, today=TODAY)
    assert len(lead.signals) == 2

    s0 = lead.signals[0]
    assert s0.type == "job_finance_lead"                     # type passthrough
    assert s0.date == "2026-07-01"                           # date <- event_date
    assert s0.date_confidence == "high"                      # always high
    assert s0.plain_words_description == "posted a controller role"  # <- evidence_text

    s1 = lead.signals[1]
    assert s1.type == "funding_form_d"
    assert s1.date == "2026-06-15"
    assert s1.date_confidence == "high"
    assert s1.plain_words_description == "filed a form d"


# --------------------------------------------------------------------------
# adapt_leadgen_lead — freshness from the PRIMARY signal's event_date
# --------------------------------------------------------------------------

def test_freshness_fresh_within_window():
    row = _row(signals=[{"type": "job_finance_lead", "event_date": "2026-07-01", "evidence_text": "x"}])
    assert adapt_leadgen_lead(row, today=TODAY).freshness == "fresh"


def test_freshness_boundary_at_window_edge():
    # exactly FRESH_WINDOW_DAYS old -> still fresh; one day past -> stale
    edge = (TODAY - timedelta(days=config.FRESH_WINDOW_DAYS)).isoformat()
    past = (TODAY - timedelta(days=config.FRESH_WINDOW_DAYS + 1)).isoformat()
    fresh = _row(signals=[{"type": "job_finance_lead", "event_date": edge, "evidence_text": "x"}])
    stale = _row(signals=[{"type": "job_finance_lead", "event_date": past, "evidence_text": "x"}])
    assert adapt_leadgen_lead(fresh, today=TODAY).freshness == "fresh"
    assert adapt_leadgen_lead(stale, today=TODAY).freshness == "stale"


def test_freshness_stale_when_old():
    row = _row(signals=[{"type": "job_finance_lead", "event_date": "2026-05-01", "evidence_text": "x"}])
    assert adapt_leadgen_lead(row, today=TODAY).freshness == "stale"


def test_freshness_stale_when_no_signals():
    row = _row(signals=[])
    lead = adapt_leadgen_lead(row, today=TODAY)
    assert lead.signals == []
    assert lead.freshness == "stale"                         # missing primary signal -> stale


def test_freshness_stale_when_event_date_missing():
    row = _row(signals=[{"type": "job_finance_lead", "evidence_text": "x"}])  # no event_date
    assert adapt_leadgen_lead(row, today=TODAY).freshness == "stale"


def test_freshness_driven_by_primary_signal_only():
    # the PRIMARY (first) signal is stale even though a later signal is fresh
    row = _row(
        signals=[
            {"type": "job_finance_lead", "event_date": "2026-05-01", "evidence_text": "old"},
            {"type": "funding_form_d", "event_date": "2026-07-19", "evidence_text": "new"},
        ]
    )
    assert adapt_leadgen_lead(row, today=TODAY).freshness == "stale"


# --------------------------------------------------------------------------
# adapt_leadgen_lead — id: row["id"] else a synthesized leadgen:... id
# --------------------------------------------------------------------------

def test_id_uses_row_id_when_present():
    assert adapt_leadgen_lead(_row(id="abc123"), today=TODAY).id == "abc123"


def test_id_synthesized_when_absent():
    lead = adapt_leadgen_lead(
        _row(id=None, name="Acme Corp", niche="cfo", state="CA"), today=TODAY
    )
    assert lead.id == "leadgen:cfo-acme-corp-ca"             # niche+company+state slug


# --------------------------------------------------------------------------
# snapshot_for_niche — stub mode (env LEADGEN_INVENTORY_DIR) + validation
# --------------------------------------------------------------------------

def _write_inventory(tmp_path, niche, rows, taxonomy):
    (tmp_path / f"{niche}-leads.json").write_text(json.dumps({"leads": rows}))
    (tmp_path / "taxonomy.json").write_text(json.dumps({"taxonomy": taxonomy}))


def test_snapshot_for_niche_stub_serves_adapted_leads_and_taxonomy(tmp_path, monkeypatch):
    rows = [
        _row(id="l1", name="Acme", niche="cfo",
             signals=[{"type": "job_finance_lead", "event_date": "2026-07-01", "evidence_text": "a"}]),
        _row(id="l2", name="Beta", niche="cfo", signal_type="funding_form_d",
             signals=[{"type": "funding_form_d", "event_date": "2026-07-05", "evidence_text": "b"}]),
    ]
    taxonomy = {"healthcare": ["dental"], "fintech": []}
    _write_inventory(tmp_path, "cfo", rows, taxonomy)
    monkeypatch.setenv("LEADGEN_INVENTORY_DIR", str(tmp_path))

    snap = snapshot_for_niche("cfo", today=TODAY)

    leads = snap.leads()                                     # adapted Lead objects
    assert all(isinstance(lead, Lead) for lead in leads)
    assert {lead.id for lead in leads} == {"l1", "l2"}
    by_id = {lead.id: lead for lead in leads}
    assert by_id["l1"].company == "Acme"                     # company <- name (adapted)
    assert by_id["l2"].value_prop == "growing fast, could use finance help"  # <- insight
    assert by_id["l2"].signal_type == "funding_form_d"

    # .leads(**params) filters the adapted inventory
    assert [lead.id for lead in snap.leads(signal_type="funding_form_d")] == ["l2"]

    # .niches() returns the taxonomy from taxonomy.json
    assert snap.niches() == taxonomy


def test_snapshot_for_niche_rejects_unknown_niche(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADGEN_INVENTORY_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        snapshot_for_niche("insurance", today=TODAY)


def test_valid_niches_are_the_five():
    assert VALID_NICHES == frozenset({"accounting", "cfo", "mssp", "msp", "cloud"})


def test_clean_company_name_strips_artifacts_only():
    from system_b.clients.inventory import _clean_company_name
    # clear registration artifact + doubled whitespace get removed
    assert _clean_company_name("Intermezzo Inc. / DE /") == "Intermezzo Inc."
    assert _clean_company_name("Foo  Bar   Inc") == "Foo Bar Inc"
    # conservative: real names (even short/odd ones) pass through untouched
    for n in ["Morreale", "Good Trouble", "Acme LLC", "Optimus Property Management, LLC"]:
        assert _clean_company_name(n) == n


# --------------------------------------------------------------------------
# Blob mode (LEADGEN_BLOB_BASE_URL) + freshness guard
# --------------------------------------------------------------------------

_BLOB_BASE = "https://store.public.blob.vercel-storage.com"


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def _blob_doc(*, generated_at="2026-07-20", rows=None):
    rows = rows if rows is not None else [_row(id="b1", name="Blobco")]
    return {"generated_at": generated_at, "niche": "cfo", "count": len(rows), "leads": rows}


def _fake_httpx(monkeypatch, *, leads_doc, taxonomy=None, record=None):
    def fake_get(url, **kw):
        if record is not None:
            record.append(url)
        if url.endswith("taxonomy.json"):
            return _FakeResp({"taxonomy": taxonomy or {}})
        return _FakeResp(leads_doc)
    monkeypatch.setattr(inv.httpx, "get", fake_get)


def test_blob_mode_reads_adapts_and_carries_source_url(monkeypatch):
    urls: list[str] = []
    doc = _blob_doc(rows=[_row(
        id="b1", name="Blobco",
        signals=[{"type": "job_finance_lead", "event_date": "2026-07-19",
                  "evidence_text": "posted a controller role",
                  "source_url": "https://jobs/blobco"}],
    )])
    monkeypatch.setenv("LEADGEN_BLOB_BASE_URL", _BLOB_BASE)
    monkeypatch.delenv("LEADGEN_INVENTORY_DIR", raising=False)
    _fake_httpx(monkeypatch, leads_doc=doc, taxonomy={"healthcare": ["dental"]}, record=urls)

    snap = snapshot_for_niche("cfo", today=TODAY)
    leads = snap.leads()
    assert [lead.company for lead in leads] == ["Blobco"]
    assert leads[0].primary_source_url == "https://jobs/blobco"     # source_url survives
    assert snap.niches() == {"healthcare": ["dental"]}              # taxonomy from blob
    assert any(u.endswith("cfo-leads.json") for u in urls)          # correct pathname fetched


def test_freshness_refuses_stale_inventory(monkeypatch):
    monkeypatch.setenv("LEADGEN_BLOB_BASE_URL", _BLOB_BASE)
    monkeypatch.delenv("LEADGEN_INVENTORY_DIR", raising=False)
    monkeypatch.delenv("LEADGEN_ALLOW_STALE", raising=False)
    _fake_httpx(monkeypatch, leads_doc=_blob_doc(generated_at="2026-07-01"))  # 19 days old
    with pytest.raises(inv.StaleInventoryError):
        snapshot_for_niche("cfo", today=TODAY)


def test_freshness_allow_stale_bypasses(monkeypatch):
    monkeypatch.setenv("LEADGEN_BLOB_BASE_URL", _BLOB_BASE)
    monkeypatch.delenv("LEADGEN_INVENTORY_DIR", raising=False)
    monkeypatch.setenv("LEADGEN_ALLOW_STALE", "1")
    _fake_httpx(monkeypatch, leads_doc=_blob_doc(generated_at="2026-07-01"))
    snap = snapshot_for_niche("cfo", today=TODAY)                   # no raise
    assert snap.leads()


def test_freshness_missing_generated_at_is_allowed(monkeypatch):
    monkeypatch.setenv("LEADGEN_BLOB_BASE_URL", _BLOB_BASE)
    monkeypatch.delenv("LEADGEN_INVENTORY_DIR", raising=False)
    doc = {"leads": [_row(id="b1", name="Blobco")]}                 # no generated_at
    _fake_httpx(monkeypatch, leads_doc=doc)
    assert snapshot_for_niche("cfo", today=TODAY).leads()           # warns, does not refuse


def test_blob_takes_precedence_over_local_dir(monkeypatch, tmp_path):
    # A leftover local dir must NOT win once the blob URL is set.
    _write_inventory(tmp_path, "cfo", [_row(id="local1", name="LocalCo")], {})
    monkeypatch.setenv("LEADGEN_INVENTORY_DIR", str(tmp_path))
    monkeypatch.setenv("LEADGEN_BLOB_BASE_URL", _BLOB_BASE)
    _fake_httpx(monkeypatch, leads_doc=_blob_doc(rows=[_row(id="blob1", name="BlobCo")]))
    ids = {lead.id for lead in snapshot_for_niche("cfo", today=TODAY).leads()}
    assert ids == {"blob1"}                                         # blob, not local1


def test_no_source_configured_raises(monkeypatch):
    monkeypatch.delenv("LEADGEN_BLOB_BASE_URL", raising=False)
    monkeypatch.delenv("LEADGEN_INVENTORY_DIR", raising=False)
    with pytest.raises(RuntimeError):
        snapshot_for_niche("cfo", today=TODAY)


# --- Job-posting age cap ---------------------------------------------------


def _job_row(days_old: int) -> dict:
    d = (date(2026, 8, 4) - timedelta(days=days_old)).isoformat()
    return {
        "id": f"j{days_old}", "name": f"Co{days_old}", "domain": "c.com",
        "signal_type": "job_finance_lead", "niche": "dental",
        "signals": [{"type": "job_finance_lead", "event_date": f"{d}T00:00:00",
                     "evidence_text": "Controller", "source_url": "https://j/1"}],
    }


def test_expired_job_leads_never_enter_the_pool():
    # "is looking for a controller" must not outlive the posting.
    rows = [_job_row(3), _job_row(20), _job_row(22), _job_row(59)]
    leads = inv._adapt_rows(rows, today=date(2026, 8, 4))
    assert [lead.id for lead in leads] == ["j3", "j20"]


def test_undated_job_lead_is_dropped():
    row = _job_row(1)
    row["signals"][0]["event_date"] = None
    assert inv._adapt_rows([row], today=date(2026, 8, 4)) == []


def test_age_cap_does_not_touch_breach_leads():
    # A breach is an event that stays true; only the hiring claim decays.
    row = _job_row(90)
    row["signal_type"] = "breach_disclosed"
    row["signals"][0]["type"] = "breach_disclosed"
    leads = inv._adapt_rows([row], today=date(2026, 8, 4))
    assert len(leads) == 1
