"""M3 acceptance — prospect research (spec Step 2a).

The LLM is injected as a fake so these are deterministic and offline. What's
tested is the code that MATTERS: verbatim-evidence enforcement (a proposed
fact is kept only if it's word-for-word on the site), thin-site fallback,
taxonomy mapping, and the honesty guarantee flowing into the copy engine.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_research.py -q
"""

from __future__ import annotations

from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.research.classifier import appears_verbatim, classify, evidence_covers, locate
from system_b.research.fetcher import discover_links, html_to_text
from system_b.research.models import Evidence, ResearchResult, to_airtable_fields
from system_b.tests.test_copy import TODAY
from system_b.tests.test_gift import FakeScraper, mk

TAXONOMY = {
    "healthcare": ["dental", "veterinary", "behavioral_health"],
    "fintech": ["payments", "lending"],
    "construction": ["residential", "commercial"],
    "other": [],
    "unknown": [],
}

# Padded so total text clears THIN_MIN_CHARS (350) for the niched fixtures.
_PAD = " ".join(["our team of fractional finance leaders helps growing companies"] * 6)


def llm_const(payload):
    """A fake LLM proposer that always returns `payload` (and asserts it was
    actually consulted only when it should be)."""
    def _fn(_site):
        return payload
    return _fn


# --------------------------------------------------------------------------
# fetcher — pure helpers
# --------------------------------------------------------------------------

def test_html_to_text_strips_tags_scripts_entities():
    src = "<div>Hello <script>var x=1;</script><b>World</b></div>&amp; more"
    assert html_to_text(src) == "Hello World & more"


def test_discover_links_same_site_keyword_pages():
    html = """
      <a href="/about">About Us</a>
      <a href="/industries">Industries We Serve</a>
      <a href="https://external.com/x">External</a>
      <a href="/blog">Blog</a>
      <a href="/case-studies/acme">Case Study</a>
    """
    links = discover_links(html, "https://firm.com")
    assert links == [
        "https://firm.com/about",
        "https://firm.com/industries",
        "https://firm.com/case-studies/acme",
    ]


# --------------------------------------------------------------------------
# verbatim enforcement primitives
# --------------------------------------------------------------------------

def test_appears_verbatim_case_and_whitespace():
    assert appears_verbatim("Healthcare Startups", "we serve healthcare startups")
    assert appears_verbatim("we  serve", "we serve clients")
    assert not appears_verbatim("fintech", "we do accounting")
    assert not appears_verbatim("", "anything")


def test_locate_returns_source_url():
    site = {"https://a.com": "generic copy", "https://a.com/about": "we serve dental practices"}
    assert locate("dental practices", site) == "https://a.com/about"
    assert locate("aerospace", site) is None


# --------------------------------------------------------------------------
# classify — niched via a stated phrase
# --------------------------------------------------------------------------

def test_classify_niched_statement():
    site = {"https://h.com": f"we serve healthcare startups nationwide. {_PAD}"}
    llm = llm_const({"classification": "niched", "path": "statement",
                     "niche_phrase": "healthcare startups", "niche_guess": "healthcare"})
    r = classify(site, TAXONOMY, llm=llm)
    assert r.classification == "niched"
    assert r.match_param == ("industry", "healthcare")
    assert r.niche_phrase == "healthcare startups"
    assert r.niche_source == "site"
    assert r.evidence == [Evidence("phrase", "healthcare startups", "https://h.com")]


# --------------------------------------------------------------------------
# classify — niched via a client list (3+ verified)
# --------------------------------------------------------------------------

def test_classify_niched_client_list():
    site = {"https://d.com/clients":
            f"our clients include Bright Smile Dental, Cedar Dental Group, and Happy Teeth Dental. {_PAD}"}
    llm = llm_const({"classification": "niched", "path": "client_list", "niche_guess": "dental",
                     "clients": [{"name": "Bright Smile Dental"},
                                 {"name": "Cedar Dental Group"},
                                 {"name": "Happy Teeth Dental"}]})
    r = classify(site, TAXONOMY, llm=llm)
    assert r.classification == "niched"
    assert r.match_param == ("niche", "dental")
    assert r.niche_source == "client_list"
    assert [e.text for e in r.evidence] == ["Bright Smile Dental", "Cedar Dental Group", "Happy Teeth Dental"]
    assert all(e.kind == "client" for e in r.evidence)
    # presence-only: client-list source ALWAYS raises a mandatory review flag
    assert any("presence-only" in f for f in r.flags)


# --------------------------------------------------------------------------
# code enforcement — a fact not verbatim on the site is REJECTED
# --------------------------------------------------------------------------

def test_hallucinated_phrase_rejected_to_generalist():
    site = {"https://g.com": f"we are an accounting and advisory firm. {_PAD}"}
    llm = llm_const({"classification": "niched", "path": "statement",
                     "niche_phrase": "fintech scaleups", "niche_guess": "fintech"})
    r = classify(site, TAXONOMY, llm=llm)
    assert r.classification == "generalist"
    assert r.match_param is None
    assert r.evidence == []
    assert any("verbatim" in f for f in r.flags)


def test_client_list_insufficient_evidence_to_generalist():
    site = {"https://d.com": f"we work with Bright Smile Dental and a few others. {_PAD}"}
    llm = llm_const({"classification": "niched", "path": "client_list", "niche_guess": "dental",
                     "clients": [{"name": "Bright Smile Dental"},
                                 {"name": "Nonexistent Client LLC"},   # not on the page
                                 {"name": "Also Fake Inc"}]})
    r = classify(site, TAXONOMY, llm=llm)
    assert r.classification == "generalist"
    assert any("insufficient" in f for f in r.flags)


# --------------------------------------------------------------------------
# thin site -> generalist, and the model isn't even trusted
# --------------------------------------------------------------------------

def test_thin_site_generalist_without_calling_llm():
    def boom(_site):
        raise AssertionError("LLM must not be consulted for a thin site")
    r = classify({"https://tiny.com": "home"}, TAXONOMY, llm=boom)
    assert r.classification == "generalist"
    assert any("thin website" in f for f in r.flags)


# --------------------------------------------------------------------------
# unmappable niche -> phrase saved, but generalist for matching (spec 2b)
# --------------------------------------------------------------------------

def test_unmappable_niche_saved_but_generalist():
    site = {"https://cu.com": f"we serve credit unions across the midwest. {_PAD}"}
    llm = llm_const({"classification": "niched", "path": "statement",
                     "niche_phrase": "credit unions", "niche_guess": "credit unions"})
    r = classify(site, TAXONOMY, llm=llm)
    assert r.classification == "generalist"       # can't be matched...
    assert r.match_param is None
    assert r.niche_phrase == "credit unions"      # ...but the phrase is kept
    assert r.evidence and r.evidence[0].text == "credit unions"
    assert evidence_covers("credit unions", r)
    assert any("no taxonomy match" in f for f in r.flags)


# --------------------------------------------------------------------------
# evidence_covers — the guard other layers call before an email
# --------------------------------------------------------------------------

def test_evidence_covers_guard():
    r = ResearchResult("niched", ("industry", "healthcare"), "healthcare startups", "site",
                       [Evidence("phrase", "healthcare startups", "https://h.com")])
    assert evidence_covers("healthcare startups", r)
    assert evidence_covers("Healthcare Startups", r)      # case-insensitive
    assert not evidence_covers("we made this up", r)


# --------------------------------------------------------------------------
# Airtable write payload
# --------------------------------------------------------------------------

def test_to_airtable_fields():
    r = ResearchResult("niched", ("industry", "healthcare"), "healthcare startups", "site",
                       [Evidence("phrase", "healthcare startups", "https://h.com")],
                       flags=["a flag"])
    f = to_airtable_fields(r)
    assert f["classification"] == "niched"
    assert f["match_param"] == "industry=healthcare"
    assert f["niche_phrase"] == "healthcare startups"
    assert f["niche_source"] == "site"
    assert f["evidence"] == '[phrase] "healthcare startups" — https://h.com'
    assert f["flags"] == "a flag"

    g = to_airtable_fields(ResearchResult("generalist", None, None, "", []))
    assert g["classification"] == "generalist"
    assert g["match_param"] == "" and g["niche_phrase"] == "" and g["evidence"] == ""
    assert "niche_source" not in g                       # nothing untrue stored


# --------------------------------------------------------------------------
# End-to-end: research -> Prospect -> copy, with the phrase provably on-site
# --------------------------------------------------------------------------

def test_research_feeds_copy_and_every_claim_is_evidenced():
    site = {"https://h.com": f"we serve healthcare startups in denver. {_PAD}"}
    llm = llm_const({"classification": "niched", "path": "statement",
                     "niche_phrase": "healthcare startups", "niche_guess": "healthcare"})
    r = classify(site, TAXONOMY, llm=llm)

    prospect = Prospect(
        firm_name="Denver Health CFOs", city="Denver", state="CO",
        classification=r.classification, match_param=r.match_param,
        niche_phrase=r.niche_phrase, niche_source=r.niche_source, first_name="dana",
    )
    leads = [mk("h1", "funding_only", industry="healthcare", city="Denver", state="CO",
                date="2026-07-05", company="Acme Bio")]
    gift = build_gift(prospect, FakeScraper(leads))
    draft = build_email_1(gift, prospect, {"h1": "closed a round"}, today=TODAY)

    # the framing quotes the prospect's exact phrase...
    assert "you focus on healthcare startups" in draft.body
    # ...and that quoted phrase is backed word-for-word by saved evidence.
    assert evidence_covers("healthcare startups", r)
