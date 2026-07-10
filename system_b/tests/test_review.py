"""M4 acceptance — review card + CRM state (the go-live milestone).

Covers the Step-10 auto-flags, the assembled card, the review state machine
(approve advances stage, reject closes, edit stores the fix), and a full
end-to-end: research -> gift -> draft -> assemble card -> approve.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_review.py -q
"""

from __future__ import annotations

from system_b.clients.airtable_client import STAGES
from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift, compute_match_level
from system_b.gift.models import Gift, Prospect
from system_b.research.classifier import classify
from system_b.research.models import Evidence, ResearchResult
from system_b.review import apply_decision, assemble_review, build_card, review_flags
from system_b.review.flags import domain_matches_company
from system_b.tests.test_copy import TODAY
from system_b.tests.test_gift import FakeScraper, mk
from system_b.tests.test_research import TAXONOMY, llm_const


class FakeAirtable:
    """Records writes so tests can assert on row state."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def update(self, rid: str, fields: dict) -> dict:
        self.records.setdefault(rid, {}).update(fields)
        return {"id": rid, "fields": self.records[rid]}

    def set_stage(self, rid: str, stage: str) -> dict:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        return self.update(rid, {"stage": stage})

    def get(self, rid: str) -> dict:
        return {"id": rid, "fields": self.records.get(rid, {})}


def _gift(leads, prospect, *, all_niche=False, geo="city", shape="plural", what="mixed") -> Gift:
    return Gift(
        leads=leads, best_lead=leads[0], gift_size=len(leads),
        all_niche=all_niche, geo_level=geo, subject_shape=shape,
        what_category=what, best_lead_level=compute_match_level(leads[0], prospect),
    )


# --------------------------------------------------------------------------
# auto-flags
# --------------------------------------------------------------------------

def test_review_flags_kitchen_sink():
    p = Prospect(
        firm_name="H", city="Denver", state="CO", classification="niched",
        match_param=("industry", "healthcare"), niche_source="site",
    )
    leads = [
        mk("a", "double_signal", industry="healthcare", city="Denver", state="CO",
           freshness="stale", domain=None, niche=None),
        mk("b", "cfo_wanted", industry="healthcare", city="Denver", state="CO",
           date_confidence="low", domain=None),
    ]
    g = _gift(leads, p, all_niche=True, geo="city", shape="singular", what="raised")
    flags = review_flags(p, g)
    joined = "\n".join(flags)
    assert "cfo_wanted" in joined                        # low-confidence live check
    assert "LLM-classified" in joined                    # niche came from the model
    assert "null-niche" in joined                        # niche is None
    assert "domainless" in joined                        # domain None
    assert "registered address" in joined                # funding/double + geo city
    assert "double_signal" in joined                     # same-company check
    assert "stale lead" in joined                        # stale used
    assert "only 2 lead" in joined                       # gift < 3


def test_domain_matcher_conservative():
    # gross mismatch -> flag
    assert not domain_matches_company("Poaster Technologies Inc.", "warp.co")
    assert not domain_matches_company("Acme Plumbing", "salesforce.com")
    # acronyms / variants / vowel-drops / branded-ish -> no flag (false positives avoided)
    for n, d in [("Center for the Visually Impaired", "cviga.org"),
                 ("Herrmann Global", "herrmanglobal.com"), ("Ghost", "ghst.io"),
                 ("Content Raven, Inc.", "contentraven.com"), ("Iq Sig", "iqsig.com"),
                 # acronym must survive entity suffixes (Inc / P.A.)
                 ("Community Foundation Partnership, Inc.", "cfpartner.org"),
                 ("Lawrenceville Plasma Physics, Inc.", "lppfusion.com"),
                 ("Young,Berman,Karpf & Karpf, P.A.", "ybkklaw.com")]:
        assert domain_matches_company(n, d), (n, d)
    assert not domain_matches_company("UserFirst Software, Inc.", "leanlaw.com")  # real mismatch kept
    assert domain_matches_company("Anything", None)   # domainless handled elsewhere


def test_domain_mismatch_flag_fires():
    p = Prospect(firm_name="G", city="Denver", state="CO", classification="generalist", match_param=None)
    lead = mk("x", "funding_only", city="Denver", state="CO", company="Poaster Technologies Inc.", domain="warp.co")
    g = _gift([lead], p, all_niche=False, geo="city")
    flags = review_flags(p, g)
    assert any("may not belong to" in f for f in flags)


def test_review_flags_bare_companies_and_generalist():
    p = Prospect(firm_name="G", city="Boise", state="ID", classification="generalist", match_param=None)
    leads = [
        mk("x", "funding_only", city="Reno", state="NV"),
        mk("y", "hiring_only", city="Austin", state="TX", finance_grade="weak"),
    ]
    g = _gift(leads, p, all_niche=False, geo="none", shape="plural", what="mixed")
    flags = review_flags(p, g)
    joined = "\n".join(flags)
    assert 'bare "companies" subject' in joined
    assert "weak finance_grade" in joined
    assert "LLM-classified" not in joined                # generalist: no niche claim


def test_review_flags_fold_research_and_dollar():
    p = Prospect(firm_name="H", city="Denver", state="CO", classification="niched",
                 match_param=("industry", "healthcare"), niche_source="client_list")
    lead = mk("f", "hiring_only", industry="healthcare", city="Denver", state="CO", finance_grade="medium")
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"f": "posted a $200k finance role"}, today=TODAY)
    research = ResearchResult("niched", ("industry", "healthcare"), None, "client_list",
                              [], flags=["client-list niche is presence-only — verify these are real clients"])
    flags = review_flags(p, g, research, draft)
    joined = "\n".join(flags)
    assert "presence-only" in joined                     # from research
    assert "dollar amount" in joined                     # from the draft
    # research flag not duplicated even though niche_source is also client_list
    assert sum("presence-only" in f for f in flags) == 1


# --------------------------------------------------------------------------
# card
# --------------------------------------------------------------------------

def test_build_card_has_all_sections():
    p = Prospect(firm_name="Denver Health CFOs", city="Denver", state="CO",
                 classification="niched", match_param=("industry", "healthcare"),
                 niche_phrase="healthcare startups", niche_source="site", first_name="dana")
    leads = [
        mk("h1", "funding_only", industry="healthcare", city="Denver", state="CO", company="Acme Bio", domain=None),
        mk("h2", "hiring_only", industry="healthcare", city="Denver", state="CO", company="Vitals Co", finance_grade="medium"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, {"h1": "closed a round", "h2": "posted a controller"}, today=TODAY)
    research = ResearchResult("niched", ("industry", "healthcare"), "healthcare startups", "site",
                              [Evidence("phrase", "healthcare startups", "https://h.com")])
    flags = review_flags(p, g, research, draft)
    card = build_card(p, g, draft, research, flags, contact={"email": "dana@h.com", "linkedin": "linkedin.com/in/dana"})

    for marker in ("REVIEW CARD", "1. PROSPECT:", "2. CLASSIFICATION: niched", "3. EVIDENCE:",
                   "4. GIFT", "5. HONESTY:", "6. FLAGS", "7. QUEUED MESSAGE:", "8. DECISION:"):
        assert marker in card
    assert "★BEST" in card
    assert "DOMAINLESS" in card                          # h1 has no domain
    assert "healthcare startups" in card                 # evidence quote
    assert "dana@h.com" in card


# --------------------------------------------------------------------------
# state machine
# --------------------------------------------------------------------------

def test_approve_advances_stage():
    fa = FakeAirtable()
    apply_decision(fa, "rec1", "approve", current_stage="researched")
    assert fa.records["rec1"]["review_status"] == "approved"
    assert fa.records["rec1"]["stage"] == "email_1_queued"


def test_reject_closes():
    fa = FakeAirtable()
    apply_decision(fa, "rec2", "reject")
    assert fa.records["rec2"]["review_status"] == "rejected"
    assert fa.records["rec2"]["stage"] == "do_not_contact"


def test_edit_stores_message_then_approve():
    fa = FakeAirtable()
    apply_decision(fa, "rec3", "edit", edited_message="hey, fixed copy")
    assert fa.records["rec3"]["review_status"] == "edited"
    assert fa.records["rec3"]["queued_message"] == "hey, fixed copy"
    assert "stage" not in fa.records["rec3"]             # edit does not advance
    apply_decision(fa, "rec3", "approve", current_stage="researched")
    assert fa.records["rec3"]["review_status"] == "approved"
    assert fa.records["rec3"]["stage"] == "email_1_queued"


def test_unknown_decision_raises():
    import pytest
    with pytest.raises(ValueError):
        apply_decision(FakeAirtable(), "r", "maybe")


# --------------------------------------------------------------------------
# assemble_review writes the row
# --------------------------------------------------------------------------

def test_assemble_review_writes_row():
    fa = FakeAirtable()
    p = Prospect(firm_name="H", city="Denver", state="CO", classification="niched",
                 match_param=("industry", "healthcare"), niche_source="site", first_name="dana")
    lead = mk("h1", "funding_only", industry="healthcare", city="Denver", state="CO")
    g = build_gift(p, FakeScraper([lead]))
    draft = build_email_1(g, p, {"h1": "closed a round"}, today=TODAY)
    assemble_review(fa, "rec9", p, g, draft)
    row = fa.records["rec9"]
    assert row["review_status"] == "pending"
    assert row["stage"] == "researched"
    assert row["all_niche"] is True
    assert row["geo_level"] == "city"
    assert row["review_card"].startswith("═══════════ REVIEW CARD")
    assert row["queued_message"].startswith("Subject: ")
    assert "sent_lead_ids" not in row                    # never clobbered at review


# --------------------------------------------------------------------------
# end-to-end go-live: research -> gift -> draft -> card -> approve
# --------------------------------------------------------------------------

def test_end_to_end_queue_and_approve():
    fa = FakeAirtable()
    site = {"https://h.com": "we serve healthcare startups in denver. " +
            " ".join(["fractional finance help for growing teams"] * 8)}
    research = classify(site, TAXONOMY, llm=llm_const(
        {"classification": "niched", "path": "statement",
         "niche_phrase": "healthcare startups", "niche_guess": "healthcare"}))

    p = Prospect(firm_name="Denver Health CFOs", city="Denver", state="CO",
                 classification=research.classification, match_param=research.match_param,
                 niche_phrase=research.niche_phrase, niche_source=research.niche_source, first_name="dana")
    leads = [
        mk("h1", "cfo_wanted", industry="healthcare", city="Denver", state="CO", date_confidence="low", domain=None),
        mk("h2", "funding_only", industry="healthcare", city="Denver", state="CO"),
    ]
    g = build_gift(p, FakeScraper(leads))
    draft = build_email_1(g, p, {l.id: "did a thing" for l in g.leads}, today=TODAY)

    fields = assemble_review(fa, "rec10", p, g, draft, research)
    # the complete card shows applicable flags (cfo_wanted live-check + domainless)
    assert "cfo_wanted" in fields["flags"]
    assert "domainless" in fields["flags"]
    assert fa.records["rec10"]["review_status"] == "pending"

    # approving transitions the stage — go-live handoff to the sender
    apply_decision(fa, "rec10", "approve", current_stage=fa.records["rec10"]["stage"])
    assert fa.records["rec10"]["review_status"] == "approved"
    assert fa.records["rec10"]["stage"] == "email_1_queued"
