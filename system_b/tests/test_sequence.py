"""The pure sequence generator: research → gift → the full 3-email sequence,
returned as a plain dict (no store, no send)."""

from __future__ import annotations

from datetime import date

from system_b.tests.test_gift import FakeScraper, mk

TODAY = date(2026, 7, 8)


def test_generate_sequence_builds_full_sequence(monkeypatch):
    import system_b.sequence.generate as gen
    from system_b.gift.models import Gift, Prospect

    lead1 = mk("l1", "job_fractional_cfo", city="Denver", state="CO")
    lead2 = mk("l2", "job_finance_lead", city="Denver", state="CO")
    lead3 = mk("l3", "funding_form_d", city="Denver", state="CO")

    prospect = Prospect(firm_name="Acme", city="Denver", state="CO",
                        classification="generalist", first_name="dana")
    gift = Gift(leads=[lead1], best_lead=lead1, gift_size=1, all_niche=False,
                geo_level="city", subject_shape="singular", what_category="hiring",
                best_lead_level=1)

    followup_leads = [lead2, lead3]

    def fake_build_gift(p, sc, *, target=3, niche_only=False, pack=None):
        # follow-ups call target=1; hand out l2 then l3, then dry up.
        if followup_leads:
            ld = followup_leads.pop(0)
            return Gift(leads=[ld], best_lead=ld, gift_size=1, all_niche=False,
                        geo_level="none", subject_shape="singular",
                        what_category="hiring", best_lead_level=None)
        return None

    describe_calls = []

    def _describe(g, p, **kw):
        describe_calls.append(len(g.leads))
        return {ld.id: "did a thing" for ld in g.leads}

    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: None)
    monkeypatch.setattr(gen, "resolve_gift", lambda research, row, sc, pack=None: (prospect, gift))
    monkeypatch.setattr(gen, "describe_leads", _describe)
    monkeypatch.setattr(gen, "build_gift", fake_build_gift)

    row = {"firm_name": "Acme", "website": "http://a.com",
           "email": "d@acme.com", "city": "Denver", "state": "CO", "first_name": "dana"}
    res = gen.generate_sequence(row, FakeScraper([]), {}, TODAY, pack_key="cfo")

    assert res["status"] == "ok"
    assert res["email"] == "d@acme.com" and res["first_name"] == "dana"
    assert res["company"] == "Acme"
    assert res["subject"]                                   # email #1 has a subject
    assert res["email_1"].startswith("hey dana,")
    assert res["email_2"] and res["email_3"]                # #2/#3 pulled l2, l3
    # email #1 uses the LLM; follow-ups use the grounded description (no LLM call)
    assert describe_calls == [1]


def test_generate_sequence_no_gift(monkeypatch):
    import system_b.sequence.generate as gen
    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: None)
    monkeypatch.setattr(gen, "resolve_gift", lambda research, row, sc, pack=None: (None, None))
    row = {"firm_name": "Acme", "website": "http://a.com", "email": "d@a.com"}
    res = gen.generate_sequence(row, FakeScraper([]), {}, TODAY, pack_key="cfo")
    assert res["status"] == "no_gift"
