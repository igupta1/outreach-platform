"""A firm's research is kept for 30 days (2026-11-13)."""

from datetime import date

from system_b.research import service
from system_b.research.models import Evidence, ResearchResult


def test_research_round_trips_and_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CACHE_PATH", tmp_path / "research-cache.json")
    monkeypatch.setattr(service, "_cache", None)
    r = ResearchResult("niched", ("industry", "construction"), "construction", "site",
                       evidence=[Evidence("phrase", "construction", "https://a.com")],
                       candidate_match_params=[("industry", "construction")],
                       candidate_phrases=["construction"], client_revenue=(1e6, None),
                       rung="bookkeeping", cpa=True)
    service.keep("https://www.A.com/", r, today=date(2026, 11, 1))
    service.flush()
    monkeypatch.setattr(service, "_cache", None)               # a new run reads the file
    back = service.cached("a.com", today=date(2026, 11, 13))
    assert back == r
    assert service.cached("a.com", today=date(2026, 12, 5)) is None   # older than 30 days


def test_a_fake_classifier_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "CACHE_PATH", tmp_path / "research-cache.json")
    monkeypatch.setattr(service, "_cache", None)
    monkeypatch.setattr(service, "fetch_site", lambda url: {url: "We serve construction."})
    service.research_prospect("https://b.com", {}, llm=lambda site: {"classification": "generalist"})
    assert service.cached("https://b.com") is None
