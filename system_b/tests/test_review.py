"""The review gate: source_url mapping, the review payload builder, the review
key on generate_sequence, and the server's data injection.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_review.py -q
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

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
                        [lead_b, None], row)


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


def test_review_lead_carries_only_what_verifies_the_claim():
    # Four fields, nothing else: who, what the copy claims, when, and the link.
    # The engine internals that used to ride along never changed a decision.
    p = _built()
    assert len(p["leads"]) == 2
    a = p["leads"][0]
    assert set(a) == {"company", "role", "date", "source_url"}
    assert a["company"] == "Acme Dental Group"
    # the review shows the SAME templated line the email sends
    assert a["role"] == "is looking for a controller"
    assert a["date"] == "2026-07-01"
    assert a["source_url"] == "https://jobs/acme"
    assert p["leads"][1]["source_url"] == "https://jobs/beta"


def test_review_generalist_has_no_niche():
    prospect = Prospect(firm_name="Generic", classification="generalist", first_name="sam")
    lead = _lead("g", "Denver Co", city="Denver", state="CO")
    gift = Gift(leads=[lead], best_lead=lead, gift_size=1, all_niche=False,
                geo_level="city", subject_shape="singular", what_category="hiring",
                best_lead_level=1)
    email1 = EmailDraft(subject="s", body="b")
    p = build_review(prospect, gift, None, email1, [], [], {"email": "s@x.com"})
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
    assert [ld["company"] for ld in review["leads"]] == ["l1", "l2"]


# --------------------------------------------------------------------------
# run.py review-path helper + serve.py data injection
# --------------------------------------------------------------------------

def test_review_path_helper():
    from system_b.run import _review_path
    assert _review_path("sequences.csv").name == "sequences.review.json"
    assert _review_path("out/foo.csv").as_posix() == "out/foo.review.json"
    assert _review_path("noext").name == "noext.review.json"


def test_card_carries_the_linkedin_url_for_connecting_in_the_same_pass():
    """The connection request goes out while reviewing, so the URL has to be on
    the card. It is already in the payload; this pins the page to using it."""
    page = (Path(__file__).resolve().parent.parent / "review" / "page.html").read_text()
    assert "p.linkedin" in page
    assert 'class:"connect"' in page
    # and a row with no URL says so rather than rendering a dead link
    assert "no linkedin" in page


def test_page_marks_rows_past_the_daily_connection_cap():
    """LinkedIn caps connection requests, so the gate has to show where to stop.
    Recomputed from LIVE cards, not row numbers, or removing a card leaves the
    line in the wrong place."""
    page = (Path(__file__).resolve().parent.parent / "review" / "page.html").read_text()
    assert re.search(r"const CONNECT_CAP = \d+;", page)
    assert 'toggle("past-cap"' in page


def test_serve_renders_and_injects(tmp_path):
    from system_b.review import serve
    doc = {"pack": "cfo", "generated_at": "2026-07-20", "valid_count": 1, "skipped": [],
           "prospects": [_built()]}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    html = serve.render(path).decode("utf-8")
    assert "__REVIEW_DATA__" not in html          # placeholder was replaced
    assert "Beacon" in html                        # prospect data is embedded
    assert "prospect" in html                      # page shell present


# --- personalization tiers: the review gate's sort, and the CSV's row order ---

from system_b.review.payload import _personalization  # noqa: E402


def _pg(*, niche=None, source="site", named=(), revenue=None, geo="city", all_niche=None):
    """A (prospect, gift) pair shaped for the tier check."""
    p = Prospect(
        firm_name="Acme", city="Denver", state="CO",
        classification="niched" if niche else "generalist",
        match_param=("industry", niche) if niche else None,
        niche_source=source, client_names=list(named), client_revenue=revenue,
    )
    lead = _lead("l1", "Lead Co", city="Denver", state="CO")
    g = Gift(
        leads=[lead], best_lead=lead, gift_size=1,
        all_niche=bool(niche) if all_niche is None else all_niche,
        geo_level=geo, subject_shape="singular", what_category="hiring",
        best_lead_level=1,
    )
    return p, g


def _rank(**kw):
    return _personalization(*_pg(**kw))["rank"]


def test_tiers_are_ordered_strongest_first():
    assert _rank(niche="healthcare", source="client_list",
                 named=["MAPS", "Public Justice Foundation"]) == 1
    assert _rank(niche="healthcare", revenue=(2e6, 10e6)) == 2
    assert _rank(niche="healthcare") == 3
    assert _rank(revenue=(2e6, 10e6), geo="city") == 4
    assert _rank(revenue=(2e6, 10e6), geo="state") == 5
    assert _rank(geo="city") == 6
    assert _rank(geo="state") == 7
    assert _rank(geo="none") == 8


def test_tier_follows_the_copy_gates_not_the_raw_data():
    """A prospect can CARRY data the opener never uses. Ranking on the data
    would sort emails by what we know rather than by what we said."""
    # client-list openers name real clients and skip revenue entirely
    assert _rank(niche="healthcare", source="client_list",
                 named=["MAPS", "Public Justice"], revenue=(2e6, 10e6)) == 1
    # one nameable client is below the two the copy requires -> not tier 1
    assert _rank(niche="healthcare", source="client_list", named=["MAPS"]) == 3
    # a niche the gift cannot back is not claimed in copy, so it cannot rank as one
    assert _rank(niche="healthcare", all_niche=False, geo="city") == 6


def test_tier_carries_a_human_label():
    out = _personalization(*_pg(niche="healthcare", revenue=(2e6, 10e6)))
    assert out == {"rank": 2, "label": "niche + revenue"}


def test_payload_exposes_the_levers_for_the_card():
    p, g = _pg(niche="healthcare", revenue=(1e6, 10e6))
    email1 = EmailDraft(subject="s", body="b")
    out = build_review(p, g, None, email1, [], [], {"email": "a@b.co"})
    assert out["personalization"]["rank"] == 2
    assert out["revenue"] == "$1m-$10m"
