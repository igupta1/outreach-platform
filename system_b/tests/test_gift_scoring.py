"""The 2026-10-30 gift-scoring pass, offline.

  - a firm never sees one organization twice in its sequence (email 2 named an
    email-1 organization under another record, or by the same name, in 21 of
    1,076 simulated sequences);
  - a second contact at a firm is handed other organizations; other firms are
    not blocked (config.EXCLUSIVE_PER_REGION is off);
  - a held or unworded type never enters a gift, and the morning check says so;
  - a gift that reaches past the prospect's state names no place of theirs.
"""

from __future__ import annotations

import json
import sys
from datetime import date

from system_b.clients.scraper_client import SnapshotScraper
from system_b.copy.email import build_email_1
from system_b.gift import engine
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import pack_for
from system_b.sequence.generate import _followup_drafts

NP = "nonprofit_grant_no_finance_officer"
QC = "nonprofit_questioned_costs"
DB = "construction_federal_award_davis_bacon"
TODAY = date(2026, 10, 30)


def lead(name, signal_type=NP, *, city="Houston", state="TX", industry="nonprofit",
         ident=None, score=50.0):
    return Lead(
        id=f"{signal_type}:{name}:{city}", company=name, city=city, state=state,
        industry=industry, signal_type=signal_type, score=score, freshness="fresh",
        entity_id=ident or f"ein:{name}",
        signals=[Signal(type=signal_type, date="2026-10-01", date_confidence="high",
                        plain_words_description="record", source_url="https://x.org",
                        payload={"fac_material_weakness": True} if signal_type == NP else {})],
    )


def sc(leads):
    return SnapshotScraper(leads, taxonomy={})


HOUSTON = dict(firm_name="AP CPA PLLC", city="Houston", state="TX")


# --- one organization, once per firm -----------------------------------------


def test_email_two_never_names_an_email_one_organization_under_another_record():
    """Walnut Hills Redevelopment Foundation: its audit finding in email 1, its
    questioned costs (same EIN, another record) in email 2."""
    charities = [lead(f"Charity {i}", score=90 - i) for i in range(3)]
    same_org = lead("Charity 0", QC, ident="ein:Charity 0")
    other = lead("Other Charity", QC)
    s = sc([*charities, same_org, other])
    p = Prospect(**HOUSTON)
    gift = build_gift(p, s)
    assert {ld.company for ld in gift.leads} == {"Charity 0", "Charity 1", "Charity 2"}
    _, _, leads = _followup_drafts(p, gift, s, pack_for("accounting"), TODAY)
    assert leads[0].company == "Other Charity"


def test_email_two_never_repeats_an_email_one_name():
    charities = [lead(f"Charity {i}", score=90 - i) for i in range(3)]
    namesake = lead("Charity 1", ident="ein:another-charity-1", city="Dallas")
    other = lead("Dallas Charity", city="Dallas")
    s = sc([*charities, namesake, other])
    p = Prospect(**HOUSTON)
    gift = build_gift(p, s)
    _, _, leads = _followup_drafts(p, gift, s, pack_for("accounting"), TODAY)
    assert leads[0].company == "Dallas Charity"


def _run(tmp_path, monkeypatch, rows, leads_by_firm, extra_args=()):
    import system_b.run as run

    apollo = tmp_path / "apollo.csv"
    apollo.write_text("x\n")
    seen = []

    def fake(p, *a, **k):
        seen.append(dict(p))
        return {"firm": p["firm_name"], "status": "ok", "company": p["firm_name"],
                "email": p["email"], "gift_size": 1, "pack": "cfo", "voice_source": "site",
                "lead_identities": leads_by_firm[p["email"]],
                "review": {"niche": "nonprofit", "personalization": {"rank": 1}}}
    monkeypatch.setattr(run, "read_apollo_csv", lambda path: [dict(r) for r in rows])
    monkeypatch.setattr(run, "load_taxonomy", lambda: {})
    monkeypatch.setattr(run, "snapshot_all_magnets", lambda today=None: None)
    monkeypatch.setattr(run.config, "require", lambda *a: None)
    monkeypatch.setattr(run, "generate_sequence", fake)
    monkeypatch.setattr(sys, "argv", [
        "run", "--in", str(apollo), "--out", str(tmp_path / "s.csv"),
        "--ledger", str(tmp_path / "seen.csv"),
        "--allocations", str(tmp_path / "alloc.csv"), "--skip-naturalness", *extra_args,
    ])
    run.main()
    return {r["email"]: r["blocked_identities"] for r in seen}


def test_a_second_contact_at_a_firm_is_handed_other_organizations(tmp_path, monkeypatch):
    rows = [{"firm_name": "Acme CPA", "state": "TX", "email": "a@acme.com"},
            {"firm_name": "Rival CPA", "state": "TX", "email": "r@rival.com"},
            {"firm_name": "ACME CPA", "state": "TX", "email": "b@acme.com"}]
    leads = {"a@acme.com": ["ein:1"], "r@rival.com": ["ein:1"], "b@acme.com": ["ein:2"]}
    blocked = _run(tmp_path, monkeypatch, rows, leads)
    assert blocked == {"a@acme.com": frozenset(), "r@rival.com": frozenset(),
                       "b@acme.com": frozenset({"ein:1"})}
    # Recorded for every firm, as before.
    assert (tmp_path / "alloc.csv").read_text().count("ein:1") == 2


def test_a_redraft_with_ignore_ledger_is_not_blocked_by_its_own_last_run(tmp_path, monkeypatch):
    (tmp_path / "alloc.csv").write_text(
        "lead,region,firm,allocated_on\nein:1,tx,acme cpa,2026-10-29\n")
    rows = [{"firm_name": "Acme CPA", "state": "TX", "email": "a@acme.com"}]
    assert _run(tmp_path, monkeypatch, rows, {"a@acme.com": ["ein:1"]},
                ["--ignore-ledger"]) == {"a@acme.com": frozenset()}
    assert _run(tmp_path, monkeypatch, rows, {"a@acme.com": ["ein:1"]}) == \
        {"a@acme.com": frozenset({"ein:1"})}


# --- only worded, approved types ---------------------------------------------


def test_a_held_type_never_enters_a_gift(monkeypatch):
    held = lead("Held Co", "plan_audit_first_due", industry="other")
    ok = lead("Charity", score=1)
    monkeypatch.setattr(engine, "HELD_TYPES", frozenset({"plan_audit_first_due"}))
    assert [ld.company for ld in build_gift(Prospect(**HOUSTON), sc([held, ok])).leads] == \
        ["Charity"]


def test_a_type_outreach_has_no_words_for_never_enters_a_gift():
    """It used to rank just above Row 8 and render through the job-post path."""
    new = lead("Cannabis Co", "a_source_wired_upstream_first", industry="other", score=99)
    assert build_gift(Prospect(**HOUSTON), sc([new])) is None
    assert engine.giftable_type(NP) and not engine.giftable_type("a_source_wired_upstream_first")
    assert engine.giftable_type("job_finance_lead")            # the IT packs' inventory


def test_the_morning_check_names_types_that_never_enter_a_gift(tmp_path, monkeypatch):
    from system_b import morning

    monkeypatch.setattr(morning, "INVENTORY_DIR", tmp_path)
    monkeypatch.setattr(morning, "MAGNETS", {"nonprofit": "nonprofit-leads.json"})
    (tmp_path / "nonprofit-leads.json").write_text(json.dumps({
        "generated_at": "2026-10-30T00:00:00Z", "count": 3,
        "leads": [{"signal_type": NP}, {"signal_type": "mystery_type"},
                  {"signal_type": "mystery_type"}]}))
    problems, warnings = morning.check(today=TODAY)
    assert problems == []
    assert any("2 lead(s) never enter a gift" in w and "mystery_type 2" in w for w in warnings)


# --- past the prospect's own state: no place of theirs is named ---------------


def test_a_gift_from_the_bordering_states_names_no_place_of_theirs():
    lincoln = Prospect(firm_name="Filaments", city="Lincoln", state="NE", first_name="Andrew")
    far = [lead("Food Bank Of Siouxland", city="Sioux City", state="IA"),
           lead("Child Care Links", city="Hutchinson", state="KS"),
           lead("Ladder Up", city="Chicago", state="IL")]
    gift = build_gift(lincoln, sc(far))
    # Iowa and Kansas border Nebraska; Illinois comes from the nationwide level.
    assert sorted(ld.state for ld in gift.leads[:2]) == ["IA", "KS"]
    assert gift.leads[2].state == "IL"
    assert gift.geo_level == "none" and not gift.all_niche
    email = build_email_1(gift, lincoln, today=TODAY, pack=pack_for("cfo"),
                          include_signoff=False)
    text = (email.subject + " " + email.body).lower()
    assert "lincoln" not in text and "nebraska" not in text and "based in" not in text
    assert "sioux city, IA" in email.body                      # each lead says where it is


def test_the_own_state_fills_before_any_bordering_one():
    here = lead("Here Lien Co", "state_tax_lien", city="Austin", industry="other")
    near = lead("Shreveport Charity", city="Shreveport", state="LA")
    assert [ld.company for ld in build_gift(Prospect(**HOUSTON), sc([near, here]),
                                            target=1).leads] == ["Here Lien Co"]


# --- rotation among equals, and where each lead is ---------------------------


def test_equally_strong_leads_rotate_per_firm_and_never_beat_a_stronger_one():
    equal = [lead(f"Charity {i}", score=80) for i in range(12)]
    best = lead("Best Charity", score=95)
    s = sc([*equal, best])
    gifts = {f: [ld.company for ld in build_gift(Prospect(firm_name=f, city="Houston",
                                                          state="TX"), s).leads]
             for f in ("Acme CPA", "Ledger Bridge", "Peach CFO", "Denman & Co")}
    assert all(g[0] == "Best Charity" for g in gifts.values())     # never weakened
    assert len({tuple(g) for g in gifts.values()}) > 1               # firms differ
    again = build_gift(Prospect(firm_name="Acme CPA", city="Houston", state="TX"), s)
    assert [ld.company for ld in again.leads] == gifts["Acme CPA"]   # deterministic


def test_rotation_never_reorders_job_posts():
    from system_b.gift.engine import rotation
    job = lead("Hiring Co", "job_finance_lead")
    assert rotation(job, "Acme CPA") == 0 and rotation(lead("C"), None) == 0


def test_city_state_display():
    from system_b.copy.lex import city_state_display
    assert city_state_display("Portland", "Oregon") == "portland, OR"
    assert city_state_display("Bangor", "me") == "bangor, ME"
    assert city_state_display("Toronto", "Ontario") == "toronto"
    assert city_state_display(None, "TX") == ""


def test_near_ties_rotate_within_a_band_and_never_past_one(monkeypatch):
    """Scores 80-84 are one band (config.NEAR_TIE_POINTS = 5): each firm gets
    its own order among them; 85 always comes first, and a stronger TYPE first
    of all, whatever its score."""
    from system_b import config
    band = [lead(f"Charity {i}", QC, score=80 + i % 5) for i in range(10)]
    s = sc([*band, lead("Top Of Band", QC, score=85), lead("Flagged", NP, score=1)])
    firms = ("Acme CPA", "Ledger Bridge", "Peach CFO", "Denman & Co", "Apex Books")
    gifts = [[ld.company for ld in build_gift(Prospect(firm_name=f, city="Houston",
                                                       state="TX"), s).leads] for f in firms]
    assert all(g[:2] == ["Flagged", "Top Of Band"] for g in gifts)
    assert len({g[2] for g in gifts}) > 1
    # 0 = exact ties only: the highest score in the band wins for everyone.
    monkeypatch.setattr(config, "NEAR_TIE_POINTS", 0)
    exact = {build_gift(Prospect(firm_name=f, city="Houston", state="TX"), s).leads[2].company
             for f in firms}
    assert exact <= {"Charity 4", "Charity 9"}
