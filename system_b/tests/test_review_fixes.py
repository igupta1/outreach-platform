"""Fixes from the 2026-10-25 review of the first batch, end to end. Offline:
research, the inventory and the model are stubbed.

  - email 2 follows email 1's KIND of lead (a Houston firm's nonprofit email
    was followed by an Arizona contractor);
  - firms matched only on location are drafted last.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date

from system_b.clients.scraper_client import SnapshotScraper
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for
from system_b.sequence.generate import _followup_drafts

NP = "nonprofit_grant_no_finance_officer"
DB = "construction_federal_award_davis_bacon"
TODAY = date(2026, 10, 25)


def lead(name, signal_type, *, city="Houston", state="TX", industry="nonprofit"):
    return Lead(
        id=name, company=name, city=city, state=state, industry=industry,
        signal_type=signal_type, score=50.0, freshness="fresh", entity_id=f"uei:{name}",
        signals=[Signal(type=signal_type, date="2026-10-01", date_confidence="high",
                        plain_words_description="record",
                        payload={"fac_material_weakness": True} if signal_type == NP else {})],
    )


def test_email_two_follows_email_ones_kind_before_any_nearby_lead():
    charities = [lead(f"Charity {i}", NP) for i in range(3)]
    builder = lead("Houston Builder", DB, industry="construction")
    dallas = lead("Dallas Charity", NP, city="Dallas")
    sc = SnapshotScraper([*charities, builder, dallas], taxonomy={})
    houston = Prospect(firm_name="AP CPA PLLC", city="Houston", state="TX")
    gift = build_gift(houston, sc, target=3, pack=pack_for("accounting"))
    assert [ld.company for ld in gift.leads] == ["Charity 0", "Charity 1", "Charity 2"]

    drafts, _, leads = _followup_drafts(houston, gift, sc, pack_for("accounting"), TODAY)
    assert leads[0].company == "Dallas Charity"
    assert drafts[0].body.startswith("one more in texas: Dallas Charity in dallas had weak")

    # With no lead of that kind anywhere, a nearby lead still beats no email 2.
    sc = SnapshotScraper([*charities, builder], taxonomy={})
    houston = Prospect(firm_name="AP CPA PLLC", city="Houston", state="TX")
    gift = build_gift(houston, sc, target=3, pack=pack_for("accounting"))
    _, _, leads = _followup_drafts(houston, gift, sc, pack_for("accounting"), TODAY)
    assert leads[0].company == "Houston Builder"


def _run(tmp_path, monkeypatch, rows, results, target):
    import system_b.run as run

    apollo = tmp_path / "apollo.csv"
    apollo.write_text("x\n")
    out = tmp_path / "sequences.csv"
    by_firm = {r["firm_name"]: res for r, res in zip(rows, results)}
    monkeypatch.setattr(run, "read_apollo_csv", lambda path: [dict(r) for r in rows])
    monkeypatch.setattr(run, "load_taxonomy", lambda: {})
    monkeypatch.setattr(run, "snapshot_all_magnets", lambda today=None: None)
    monkeypatch.setattr(run.config, "require", lambda *a: None)
    monkeypatch.setattr(run, "generate_sequence",
                        lambda p, *a, **k: dict(by_firm[p["firm_name"]]))
    monkeypatch.setattr(sys, "argv", [
        "run", "--in", str(apollo), "--out", str(out), "--target", str(target),
        "--ledger", str(tmp_path / "seen.csv"),
        "--allocations", str(tmp_path / "alloc.csv"), "--skip-naturalness",
    ])
    run.main()
    with open(out, newline="") as fh:
        firms = [r["company"] for r in csv.DictReader(fh)]
    seen = (tmp_path / "seen.csv").read_text()
    return firms, seen, json.loads((tmp_path / "sequences.review.json").read_text())


def _result(firm, *, niche, leads=()):
    return {"status": "ok", "company": firm, "email": f"{firm.lower()}@x.com",
            "pack": "cfo", "voice_source": "site", "gift_size": 3,
            "lead_identities": list(leads),
            "review": {"niche": niche, "personalization": {"rank": 2 if niche else 5}}}


def test_location_only_firms_are_drafted_only_when_the_target_needs_them(tmp_path, monkeypatch):
    rows = [{"firm_name": f, "state": "TX", "email": f"{f.lower()}@x.com"}
            for f in ("Geo1", "Ind1", "Geo2", "Ind2", "Ind3")]
    results = [_result("Geo1", niche=None), _result("Ind1", niche="nonprofit"),
               _result("Geo2", niche=None), _result("Ind2", niche="construction"),
               _result("Ind3", niche="nonprofit")]
    firms, seen, _ = _run(tmp_path, monkeypatch, rows, results, target=2)
    assert sorted(firms) == ["Ind1", "Ind2"]
    # A held firm is not on the ledger, so a later run tries it again.
    assert "geo1@x.com" not in seen and "ind1@x.com" in seen


def test_location_only_firms_fill_a_short_batch_in_file_order(tmp_path, monkeypatch):
    rows = [{"firm_name": f, "state": "TX", "email": f"{f.lower()}@x.com"}
            for f in ("Geo1", "Ind1", "Geo2", "Geo3")]
    results = [_result("Geo1", niche=None, leads=["ein:1"]),
               _result("Ind1", niche="nonprofit", leads=["ein:1"]),
               _result("Geo2", niche=None, leads=["ein:2"]),
               _result("Geo3", niche=None, leads=["ein:3"])]
    firms, _, _ = _run(tmp_path, monkeypatch, rows, results, target=3)
    # Industry match first, then location-only in file order. Geo1 shares an
    # organization with Ind1 and still goes: since 2026-10-25 any firm may get
    # any lead.
    assert sorted(firms) == ["Geo1", "Geo2", "Ind1"]


def test_two_firms_in_one_state_may_get_the_same_lead(tmp_path, monkeypatch):
    """2026-10-25, the user: any prospect may get any lead. The run no longer
    hands the gift builder a list of organizations other firms already got."""
    import system_b.run as run

    seen_rows = []
    rows = [{"firm_name": f, "state": "TX", "email": f"{f.lower()}@x.com"}
            for f in ("Ind1", "Ind2")]
    results = {r["firm_name"]: _result(r["firm_name"], niche="nonprofit", leads=["ein:1"])
               for r in rows}
    apollo = tmp_path / "apollo.csv"
    apollo.write_text("x\n")
    monkeypatch.setattr(run, "read_apollo_csv", lambda path: [dict(r) for r in rows])
    monkeypatch.setattr(run, "load_taxonomy", lambda: {})
    monkeypatch.setattr(run, "snapshot_all_magnets", lambda today=None: None)
    monkeypatch.setattr(run.config, "require", lambda *a: None)

    def fake(p, *a, **k):
        seen_rows.append(dict(p))
        return dict(results[p["firm_name"]])
    monkeypatch.setattr(run, "generate_sequence", fake)
    monkeypatch.setattr(sys, "argv", [
        "run", "--in", str(apollo), "--out", str(tmp_path / "s.csv"), "--target", "2",
        "--ledger", str(tmp_path / "seen.csv"),
        "--allocations", str(tmp_path / "alloc.csv"), "--skip-naturalness",
    ])
    run.main()
    assert all(not r.get("blocked_identities") for r in seen_rows)
    with open(tmp_path / "s.csv", newline="") as fh:
        assert sorted(r["company"] for r in csv.DictReader(fh)) == ["Ind1", "Ind2"]
