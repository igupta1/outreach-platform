"""The review gate: source_url mapping, the review payload builder, the review
key on generate_sequence, and the server's data injection.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_review.py -q
"""

from __future__ import annotations

import json
from datetime import date

from system_b.copy.email import EmailDraft
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.research.models import Evidence, ResearchResult
from system_b.review.payload import build_review

TODAY = date(2026, 7, 20)


def _lead(id, company, *, niche=None, city=None, state=None, domain="x.com",
          signal_type="job_finance_lead", url="https://jobs/x", ev="Controller"):
    return Lead(
        id=id, company=company, domain=domain, city=city, state=state, niche=niche,
        value_prop="growing fast", signal_type=signal_type, freshness="fresh",
        signals=[Signal(type=signal_type, date="2026-07-01", date_confidence="high",
                        plain_words_description=ev, source_url=url)],
    )


# --------------------------------------------------------------------------
# source_url survives the inventory adapter (was dropped before this feature)
# --------------------------------------------------------------------------

def test_adapter_carries_source_url():
    from system_b.clients.inventory import adapt_leadgen_lead
    row = {
        "id": "l1", "name": "Acme", "signal_type": "funding_form_d", "niche": "cfo",
        "signals": [{"type": "funding_form_d", "event_date": "2026-07-01",
                     "evidence_text": "filed a form d", "source_url": "https://sec.gov/d/1"}],
    }
    lead = adapt_leadgen_lead(row, today=TODAY)
    assert lead.signals[0].source_url == "https://sec.gov/d/1"
    assert lead.primary_source_url == "https://sec.gov/d/1"


def test_primary_source_url_skips_empty_signals():
    lead = Lead(id="l", company="C", signal_type="job_it_support", signals=[
        Signal(type="job_it_support", source_url=None),
        Signal(type="funding_form_d", source_url="https://sec.gov/d/2"),
    ])
    assert lead.primary_source_url == "https://sec.gov/d/2"


# --------------------------------------------------------------------------
# build_review — the per-prospect payload
# --------------------------------------------------------------------------

def _built():
    lead_a = _lead("a", "Acme Dental Group", niche="dental", city="Denver", state="CO",
                   url="https://jobs/acme")
    lead_b = _lead("b", "Beta Dental", niche="dental", url="https://jobs/beta",
                   ev="Finance Manager", domain=None)
    prospect = Prospect(firm_name="Beacon", city="Denver", state="CO",
                        classification="niched", match_param=("niche", "dental"),
                        niche_phrase="dental practices", niche_source="site",
                        niche_exclusivity="sole", first_name="dana")
    gift = Gift(leads=[lead_a], best_lead=lead_a, gift_size=1, all_niche=True,
                geo_level="none", subject_shape="singular", what_category="hiring",
                best_lead_level=3)
    research = ResearchResult(
        classification="niched", match_param=("niche", "dental"),
        niche_phrase="dental practices", niche_source="site",
        evidence=[Evidence("phrase", "dental practices", "https://beacon.com/about")],
        flags=["stated niche ok"],
    )
    email1 = EmailDraft(subject="a dental company is hiring", body="hey dana,\n\ngift...",
                        flags=["domainless lead (Beta Dental) — google the name"],
                        left_field_variant="C")
    fu2 = EmailDraft(subject="", body="found one more:",
                     flags=["domainless lead (Beta Dental) — google the name"])  # dup flag
    fu3 = EmailDraft(subject="", body="last one from me.")
    row = {"email": "dana@beacon.com", "first_name": "dana", "linkedin": "https://li/dana"}
    return build_review(prospect, gift, research, email1, [fu2, fu3],
                        {"a": "hired a controller"}, [lead_b, None], row)


def test_review_identity_and_copy():
    p = _built()
    assert p["company"] == "Beacon"
    assert p["email"] == "dana@beacon.com"
    assert p["first_name"] == "dana"
    assert p["subject"] == "a dental company is hiring"
    assert p["email_1"].startswith("hey dana,")
    assert p["email_2"] == "found one more:"
    assert p["email_3"] == "last one from me."


def test_review_classification_and_evidence():
    p = _built()
    assert p["classification"] == "niched"
    assert p["niche"] == "dental"
    assert p["match_param"] == "niche=dental"
    assert "site" in p["how_we_know"]
    assert p["niche_phrase"] == "dental practices"
    assert p["evidence"] == [{"kind": "phrase", "text": "dental practices",
                              "url": "https://beacon.com/about"}]


def test_review_flags_merged_and_deduped():
    p = _built()
    # research flag + copy flag, and the duplicate domainless flag collapses to one
    assert "stated niche ok" in p["flags"]
    assert p["flags"].count("domainless lead (Beta Dental) — google the name") == 1


def test_review_leads_include_source_url_and_followups():
    p = _built()
    assert [ld["used_in"] for ld in p["leads"]] == ["email 1", "email 2"]
    a = p["leads"][0]
    assert a["best"] is True
    assert a["source_url"] == "https://jobs/acme"
    assert a["match_level"] == 1               # niche + city (both Denver/CO) -> level 1
    # job lead: review shows the SAME templated hiring line the email uses,
    # not the raw LLM clause (which the descriptions dict passed as "hired a...").
    assert a["description"] == "is looking for a controller"
    assert a["signals"][0]["source_url"] == "https://jobs/acme"
    b = p["leads"][1]
    assert b["used_in"] == "email 2"
    assert b["domainless"] is True
    assert b["source_url"] == "https://jobs/beta"


def test_review_generalist_has_no_niche():
    prospect = Prospect(firm_name="Generic", classification="generalist", first_name="sam")
    lead = _lead("g", "Denver Co", city="Denver", state="CO")
    gift = Gift(leads=[lead], best_lead=lead, gift_size=1, all_niche=False,
                geo_level="city", subject_shape="singular", what_category="hiring",
                best_lead_level=1)
    email1 = EmailDraft(subject="s", body="b")
    p = build_review(prospect, gift, None, email1, [], {}, [], {"email": "s@x.com"})
    assert p["classification"] == "generalist"
    assert p["niche"] is None
    assert p["match_param"] is None
    assert p["evidence"] == []                 # research=None handled gracefully


# --------------------------------------------------------------------------
# generate_sequence attaches the review payload
# --------------------------------------------------------------------------

def test_generate_sequence_includes_review(monkeypatch):
    import system_b.sequence.generate as gen
    from system_b.tests.test_gift import FakeScraper, mk

    lead1 = mk("l1", "job_fractional_cfo", city="Denver", state="CO")
    lead2 = mk("l2", "job_finance_lead", city="Denver", state="CO")
    prospect = Prospect(firm_name="Acme", city="Denver", state="CO",
                        classification="generalist", first_name="dana")
    gift = Gift(leads=[lead1], best_lead=lead1, gift_size=1, all_niche=False,
                geo_level="city", subject_shape="singular", what_category="hiring",
                best_lead_level=1)
    followup_leads = [lead2]

    def fake_build_gift(p, sc, *, target=3, niche_only=False, pack=None):
        if followup_leads:
            ld = followup_leads.pop(0)
            return Gift(leads=[ld], best_lead=ld, gift_size=1, all_niche=False,
                        geo_level="none", subject_shape="singular",
                        what_category="hiring", best_lead_level=None)
        return None

    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: None)
    monkeypatch.setattr(gen, "resolve_gift", lambda research, row, sc, pack=None: (prospect, gift))
    monkeypatch.setattr(gen, "describe_leads", lambda g, p, **kw: {ld.id: "did a thing" for ld in g.leads})
    monkeypatch.setattr(gen, "build_gift", fake_build_gift)

    row = {"firm_name": "Acme", "website": "http://a.com", "email": "d@acme.com",
           "city": "Denver", "state": "CO", "first_name": "dana"}
    res = gen.generate_sequence(row, FakeScraper([]), {}, TODAY, pack_key="cfo")

    assert res["status"] == "ok"
    review = res["review"]
    assert review["company"] == "Acme"
    assert review["email"] == "d@acme.com"
    assert review["subject"] == res["subject"]
    assert review["email_1"] == res["email_1"]
    assert [ld["used_in"] for ld in review["leads"]] == ["email 1", "email 2"]


# --------------------------------------------------------------------------
# run.py review-path helper + serve.py data injection
# --------------------------------------------------------------------------

def test_review_path_helper():
    from system_b.run import _review_path
    assert _review_path("sequences.csv").name == "sequences.review.json"
    assert _review_path("out/foo.csv").as_posix() == "out/foo.review.json"
    assert _review_path("noext").name == "noext.review.json"


def test_serve_renders_and_injects(tmp_path):
    from system_b.review import serve
    doc = {"pack": "cfo", "generated_at": "2026-07-20", "valid_count": 1, "skipped": [],
           "prospects": [_built()]}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    html = serve.render(path).decode("utf-8")
    assert "__REVIEW_DATA__" not in html          # placeholder was replaced
    assert "Beacon" in html                        # prospect data is embedded
    assert "valid prospect" in html                # page shell present
