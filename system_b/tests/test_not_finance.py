"""Firms whose own site plainly sells something other than finance services
are dropped before any gift or copy, and remembered so they are never
researched again (2026-11-05). Offline: the model is a fake."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from system_b import run
from system_b.research.classifier import classify
from system_b.tests.test_gift import FakeScraper
from system_b.tests.test_research import TAXONOMY, llm_const
from system_b.tests.test_sequence import TODAY, _Research

_STAFFING = {"https://hazeltine.example": (
    "Hazeltine Executive Search. We place top accounting talent with growing companies "
    "across the country. Our recruiters find controllers, CFOs and staff accountants "
    "for permanent and interim roles. " * 4)}


def _proposal(business, phrase):
    return {"classification": "generalist", "business": business, "business_phrase": phrase}


def test_a_staffing_site_is_marked_with_its_own_words():
    r = classify(_STAFFING, TAXONOMY, llm=llm_const(_proposal("staffing", "We place top accounting talent")))
    assert r.business == "staffing" and r.business_phrase == "We place top accounting talent"
    assert any(e.kind == "business" for e in r.evidence)


def test_nothing_is_marked_without_a_verbatim_phrase_or_for_a_finance_firm():
    made_up = classify(_STAFFING, TAXONOMY, llm=llm_const(_proposal("staffing", "a recruiting agency")))
    assert made_up.business == ""                       # not on the page
    finance = classify(_STAFFING, TAXONOMY, llm=llm_const(_proposal("finance", "")))
    assert finance.business == ""
    unclear = classify(_STAFFING, TAXONOMY, llm=llm_const(_proposal("unclear", "We place")))
    assert unclear.business == ""
    thin = classify({"https://x.example": "Welcome."}, TAXONOMY,
                    llm=llm_const(_proposal("software", "Welcome.")))
    assert thin.business == ""                          # thin site: never marked


class _Staffing(_Research):
    business = "staffing"
    business_phrase = "We place top accounting talent"


def test_a_non_finance_firm_gets_no_sequence(monkeypatch):
    import system_b.sequence.generate as gen
    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: _Staffing())
    monkeypatch.setattr(gen, "resolve_gift", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    row = {"firm_name": "Hazeltine Executive Search", "website": "http://h.example",
           "email": "Dana@H.example"}
    res = gen.generate_sequence(row, FakeScraper([]), {}, TODAY, pack_key="cfo")
    assert res["status"] == "not_finance"
    assert res["not_finance"]["email"] == "dana@h.example"
    assert res["not_finance"]["business"] == "staffing"


def test_a_firm_whose_name_says_finance_is_kept(monkeypatch):
    import system_b.sequence.generate as gen
    monkeypatch.setattr(gen, "research_prospect", lambda *a, **k: _Staffing())
    monkeypatch.setattr(gen, "resolve_gift", lambda *a, **k: (None, None))
    row = {"firm_name": "Smith CPA Group", "website": "http://s.example", "email": "a@s.example"}
    assert gen.generate_sequence(row, FakeScraper([]), {}, TODAY)["status"] == "no_gift"
    assert gen.names_finance_service("Taxman Bookkeeping")
    assert not gen.names_finance_service("CFO.University")


def test_dropped_firms_are_remembered_beside_the_ledger(tmp_path: Path):
    path = tmp_path / run.NOT_FINANCE_NAME
    assert run._load_not_finance(path) == set()
    run._append_not_finance(path, [{"email": "dana@h.example", "website": "h.example",
                                    "firm_name": "Hazeltine", "business": "staffing",
                                    "evidence": "We place top accounting talent"}], date(2026, 11, 5))
    run._append_not_finance(path, [{"email": "b@x.example", "business": "software"}], date(2026, 11, 6))
    assert run._load_not_finance(path) == {"dana@h.example", "b@x.example"}
    assert path.read_text().splitlines()[0] == ",".join(run.NOT_FINANCE_COLUMNS)
