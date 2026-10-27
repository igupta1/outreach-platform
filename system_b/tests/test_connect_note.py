"""The LinkedIn connection note (2026-10-25): the gift inside LinkedIn's 300
characters, in email 1's own words, and never a half-sentence. Offline."""

from __future__ import annotations

from system_b.copy.linkedin import CONNECT_NOTE_MAX, build_connect_note
from system_b.dm import already_contacted
from system_b.gift.models import Prospect
from system_b.niches.base import pack_for
from system_b.tests.test_record_opener import DB, MW, NP, TROY, gift, lead

DASHES = "‒–—―"
CFO = pack_for("cfo")


NICHED = Prospect(firm_name="Peach Cfo", city="Atlanta", state="GA", first_name="Troy",
                  classification="niched", match_param=("industry", "nonprofit"),
                  niche_source="site")


def test_three_leads_in_email_1s_words():
    g = gift([lead(NP, MW, name="Georgia Works"), lead(NP, MW, name="Cathedral Towers"),
              lead(NP, MW, name="Hope Atlanta")], all_niche=True)
    note = build_connect_note(g, NICHED, pack=CFO)
    assert note == (
        "hey troy, saw on your site you work with nonprofits. these 3 in atlanta had "
        "weak financial controls flagged in their federal audits, and each has to show "
        "it's fixed in its next audit: Georgia Works; Cathedral Towers; Hope Atlanta.\n\n"
        "i'm an engineer and built a system that finds these. worth a look?"
    )
    assert len(note) <= CONNECT_NOTE_MAX


def test_long_names_drop_leads_not_words():
    names = ["Georgia Court Appointed Special Advocates",
             "Cathedral Towers Senior Living Community",
             "Hope Atlanta Travelers Aid Society"]
    g = gift([lead(NP, MW, name=n) for n in names], all_niche=True)
    note = build_connect_note(g, NICHED, pack=CFO)
    assert note is not None and len(note) <= CONNECT_NOTE_MAX
    assert names[0] in note                     # the best lead survives, whole
    assert names[2] not in note                 # a lead goes before a word does
    assert "this one in atlanta" in note        # and the sentence says one
    assert "finds more like it." in note        # one lead, singular
    assert note.endswith("worth a look?")


def test_every_shape_fits_and_has_no_em_dash():
    p = Prospect(firm_name="Ledger Co", city="Tampa", state="FL", first_name="Ana")
    for leads in (
        [lead(DB, {"first_contract_on_record": True}, name="Sunshine Paving", city="Tampa",
              state="FL", industry="construction")],
        [lead(NP, MW, name=f"Tampa Org {i}", city="Tampa", state="FL") for i in range(3)],
        [lead(NP, MW, name="Bay Arts", city="Tampa", state="FL"),
         lead(DB, {}, name="Gulf Build", city="Tampa", state="FL", industry="construction")],
    ):
        note = build_connect_note(gift(leads), p, pack=CFO)
        assert note is not None
        assert len(note) <= CONNECT_NOTE_MAX
        assert not any(d in note for d in DASHES)
        assert note.startswith("hey ana,")


def test_no_niche_claim_without_an_all_niche_gift():
    # Same leads, gift NOT all-niche: the note must not say "you work with nonprofits".
    g = gift([lead(NP, MW, name="Cathedral Towers")], all_niche=False)
    p = Prospect(firm_name="Peach Cfo", city="Atlanta", state="GA", first_name="Troy",
                 classification="generalist")
    note = build_connect_note(g, p, pack=CFO)
    assert note is not None
    assert "work with" not in note


def test_nothing_fits_returns_none():
    huge = "X" * 260
    g = gift([lead(NP, MW, name=huge)], all_niche=True)
    assert build_connect_note(g, TROY, pack=CFO) is None


def test_already_contacted_reads_every_ledger(tmp_path):
    (tmp_path / "seen-prospects.csv").write_text("email,first_seen\njo@acmecpa.com,2026-10-01\n")
    alloc = tmp_path / "alloc.csv"
    alloc.write_text("lead,region,firm,allocated_on\nein:1,GA,acme cpa,2026-10-02\n")
    log = tmp_path / "log.csv"
    hits = already_contacted("https://www.acmecpa.com", "Acme CPA", data=tmp_path,
                             allocations=alloc, log=log)
    assert any("emailed already" in h for h in hits)
    assert any("lead-allocations" in h for h in hits)
    assert already_contacted("https://other.com", "Other LLC", data=tmp_path,
                             allocations=alloc, log=log) == []
