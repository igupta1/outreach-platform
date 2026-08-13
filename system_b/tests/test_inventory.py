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


def test_valid_niches_are_the_six():
    assert VALID_NICHES == frozenset(
        {"bookkeeping", "accounting", "cfo", "mssp", "msp", "cloud"}
    )


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


# --- Layer 1: the unusable-lead gate ---------------------------------------

from system_b.clients.inventory import (  # noqa: E402
    _adapt_rows,
    _foreign_hirer,
    _has_id_suffix,
    _unusable_reason,
)


def _gate_row(**over):
    row = {
        "id": 1,
        "name": "Acme Paving",
        "domain": "acmepaving.com",
        "insight": "Acme Paving builds roads.",
        "signal_type": "job_finance_lead",
        "city": "Austin",
        "state": "TX",
        "signals": [{
            "type": "job_finance_lead",
            "event_date": "2026-08-01T00:00:00",
            "evidence_text": "Controller",
            "source_url": "https://example.com/j/1",
            "payload": {},
        }],
    }
    row.update(over)
    return row


def test_id_suffix_catches_the_hash_artifact():
    # The shape the fractional board actually produces.
    assert _has_id_suffix("Lifesitenews 07Cfc")
    assert _has_id_suffix("Lifesitenews Bef8C")
    assert _has_id_suffix("Plutus Health Ddb8F")


def test_id_suffix_leaves_real_brands_alone():
    # Every one of these is a real company in the live store. A rule that eats
    # them costs more than the artifacts it removes.
    for name in (
        "Love146", "Horizon3", "Imagine360", "4AIR", "JB3D", "Incodema3D",
        "Delta360", "93Energy", "TRL11", "PM2CM", "Live4Lali", "hello82",
        "SunEnergy1LLC", "Wavepoint3pl", "Enrollment123", "Transform9",
        "F3EA Inc", "3Dt Holdings", "Studio 54", "Area 51", "Sector 9",
        "Big Ten", "Deca Dence",     # letters-only trailing token, hex or not
    ):
        assert not _has_id_suffix(name), name


def test_domainless_lead_is_kept_not_dropped():
    """`gift.engine.sort_key` ranks a domainless lead below every resolvable
    company. Dropping it here would make that tiebreak dead code and cost real
    leads for a case the ranking already handles."""
    row = _gate_row(domain=None)
    assert _unusable_reason(row, _gate_lead(row)) is None


def test_clean_lead_survives():
    row = _gate_row()
    assert _unusable_reason(row, _gate_lead(row)) is None


def _gate_lead(row):
    from datetime import date as _d
    from system_b.clients.inventory import adapt_leadgen_lead
    return adapt_leadgen_lead(row, today=_d(2026, 8, 5))


def test_recruiter_posting_naming_another_company_is_dropped():
    # The real case: the lead is the recruiter, the body names the actual hirer.
    row = _gate_row(name="InforCapital, partnership", domain="inforcapital.com")
    row["signals"][0]["payload"] = {
        "description": "Amphora Equity Partners is looking for a Vice President "
                       "of Finance to lead financial operations."
    }
    reason = _unusable_reason(row, _gate_lead(row))
    assert reason is not None and "Amphora" in reason


def test_posting_naming_the_same_company_is_kept():
    # Same company, phrased differently — token overlap must save it.
    row = _gate_row(name="Shipium", domain="shipium.com")
    row["signals"][0]["payload"] = {
        "description": "About the role Shipium is looking for a Controller."
    }
    assert _unusable_reason(row, _gate_lead(row)) is None


def test_generic_opener_is_not_a_foreign_hirer():
    for opener in (
        "Our company is looking for a Controller.",
        "The company is seeking a Director of Finance.",
        "We is hiring",           # degenerate, must not match a name
    ):
        row = _gate_row()
        row["signals"][0]["payload"] = {"description": opener}
        assert _foreign_hirer(row, "Acme Paving") is None, opener


def test_missing_description_is_not_a_foreign_hirer():
    row = _gate_row()
    row["signals"][0]["payload"] = {}
    assert _foreign_hirer(row, "Acme Paving") is None


def test_adapt_rows_drops_unusable_and_keeps_the_rest():
    from datetime import date as _d
    rows = [
        _gate_row(id=1, name="Acme Paving", domain="acmepaving.com"),
        _gate_row(id=2, name="Lifesitenews 07Cfc", domain="lifesitenews.com"),
        _gate_row(id=3, name="No Domain Co", domain=None),
        _gate_row(id=4, name="Good Corp", domain="goodcorp.com"),
    ]
    kept = _adapt_rows(rows, today=_d(2026, 8, 5))
    # The hash-suffixed name goes; the domainless one stays (ranked, not dropped).
    assert [lead.company for lead in kept] == ["Acme Paving", "No Domain Co", "Good Corp"]


# --- ALL-CAPS company names stop shouting ----------------------------------

from system_b.clients.inventory import _fix_shouting, _fractional_qualifier  # noqa: E402


def test_shouting_names_are_calmed_down():
    """An ALL-CAPS name shouts inside otherwise-lowercase prose and reads as
    scraped. Every input here reached a real email."""
    cases = {
        "GROWING HOPE": "Growing Hope",
        "DEPENDABLE SERVICE PLUMBING & AIR": "Dependable Service Plumbing & Air",
        "TRUSTPOINT": "Trustpoint",
        "SUMMIT LOGISTICS GROUP LLC": "Summit Logistics Group LLC",   # LLC stays
        "ADFAC, LLC": "Adfac, LLC",
        "UPSIDEHOM, INC.": "Upsidehom, Inc.",                        # Inc. does not
        "GP INSTALLATION": "GP Installation",                        # initials stay
    }
    for raw, want in cases.items():
        assert _fix_shouting(raw) == want, raw


def test_short_single_token_acronyms_are_left_alone():
    """"Nacdd" and "Maps" would be exactly the mangling this is meant to
    prevent."""
    for name in ("NACDD", "MAPS", "SISU", "JGO", "BWXT"):
        assert _fix_shouting(name) == name, name


def test_names_that_chose_their_own_casing_are_untouched():
    for name in ("F3EA Inc", "co:census", "Orena Fragrances", "3DT Holdings", "iRobot"):
        assert _fix_shouting(name) == name, name


# --- the fractional word the title hid --------------------------------------

def _frac_row(title, description):
    return {"signals": [{"type": "job_fractional_cfo", "evidence_text": title,
                         "payload": {"title": title, "description": description}}]}


def test_qualifier_is_recovered_from_the_posting_body():
    """leadgen tags a posting fractional off the title OR the body, but the email
    prints the title — so a body-only qualifier left the subject promising a
    fractional role the lead line never showed. 17 of 23 emails in a real run."""
    assert _fractional_qualifier(
        _frac_row("Chief Financial Officer", "this is a fractional role, 10 hrs/week")
    ) == "fractional"
    assert _fractional_qualifier(
        _frac_row("Chief Financial Officer", "we need an interim CFO during the search")
    ) == "interim"
    assert _fractional_qualifier(
        _frac_row("Chief Financial Officer", "a part-time engagement")
    ) == "part-time"


def test_no_qualifier_when_the_title_already_says_it():
    assert _fractional_qualifier(_frac_row("Fractional CFO", "fractional role")) is None
    assert _fractional_qualifier(_frac_row("Interim Controller", "interim")) is None


def test_low_confidence_words_are_never_used():
    """leadgen also matches contract/consultant/advisory/temp/virtual, but those
    appear incidentally in ordinary job copy. Saying less beats saying it wrong."""
    for desc in (
        "strong contract negotiation and advisory board experience",
        "you will lead consulting engagements for our clients",
        "manage temp staffing and virtual meetings",
    ):
        assert _fractional_qualifier(_frac_row("Chief Financial Officer", desc)) is None


def test_qualifier_only_reads_the_fractional_signal():
    row = {"signals": [
        {"type": "job_finance_lead", "evidence_text": "Controller",
         "payload": {"title": "Controller", "description": "fractional work available"}},
    ]}
    assert _fractional_qualifier(row) is None
