"""Retry-with-backoff behavior for ScraperClient (the 502s in the live run).

Uses real httpx.Response objects so raise_for_status() behaves exactly like
production; the HTTP call itself is faked so nothing hits the network and
sleeps are captured instead of slept.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_scraper_client.py -q
"""

from __future__ import annotations

import httpx
import pytest

from system_b.clients.scraper_client import ScraperClient, SnapshotScraper, _is_retryable
from system_b.tests.test_gift import FakeScraper, mk


def _resp(status: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, request=httpx.Request("GET", "https://x/api/leads"))


class _FakeHttp:
    """Returns queued responses (or raises queued exceptions) per get()."""

    def __init__(self, seq: list) -> None:
        self.seq = list(seq)
        self.calls = 0

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        item = self.seq[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        pass


def _client(seq: list, **kw):
    delays: list[float] = []
    sc = ScraperClient(base_url="https://x", sleep=lambda d: delays.append(d), **kw)
    sc._client = _FakeHttp(seq)  # type: ignore[assignment]
    return sc, sc._client, delays


# --------------------------------------------------------------------------
# retry policy
# --------------------------------------------------------------------------

def test_retries_5xx_then_succeeds():
    sc, http, delays = _client([_resp(502), _resp(502), _resp(200, {"taxonomy": {"healthcare": ["dental"]}})])
    out = sc.niches()
    assert out == {"healthcare": ["dental"]}
    assert http.calls == 3                 # two retries, third ok
    assert delays == [0.5, 1.0]            # exponential backoff


def test_gives_up_after_max_attempts():
    sc, http, delays = _client([_resp(502), _resp(502), _resp(502)])
    with pytest.raises(httpx.HTTPStatusError):
        sc.niches()
    assert http.calls == 3
    assert delays == [0.5, 1.0]


def test_4xx_not_retried():
    sc, http, delays = _client([_resp(404)])
    with pytest.raises(httpx.HTTPStatusError):
        sc.niches()
    assert http.calls == 1                 # permanent — no retry
    assert delays == []


def test_connection_error_retried():
    req = httpx.Request("GET", "https://x/api/leads")
    sc, http, delays = _client([httpx.ConnectError("boom", request=req), _resp(200, {"taxonomy": {}})])
    assert sc.niches() == {}
    assert http.calls == 2
    assert delays == [0.5]


def test_is_retryable_predicate():
    req = httpx.Request("GET", "https://x")
    assert _is_retryable(httpx.HTTPStatusError("x", request=req, response=_resp(500)))
    assert _is_retryable(httpx.HTTPStatusError("x", request=req, response=_resp(503)))
    assert not _is_retryable(httpx.HTTPStatusError("x", request=req, response=_resp(404)))
    assert _is_retryable(httpx.ConnectError("x", request=req))
    assert _is_retryable(httpx.ReadTimeout("x", request=req))


def test_cache_short_circuits_second_call():
    sc, http, _ = _client([_resp(200, {"taxonomy": {"a": []}})])
    sc.niches()
    sc.niches()                            # served from cache; no second GET
    assert http.calls == 1


# --------------------------------------------------------------------------
# SnapshotScraper: same filter/sort as the live API, zero per-query calls
# --------------------------------------------------------------------------

def _universe():
    return [
        mk("a", "funding_only", industry="healthcare", city="Denver", state="CO", freshness="fresh", date="2026-07-05"),
        mk("b", "hiring_only", industry="healthcare", city="Denver", state="CO", freshness="fresh", date="2026-07-06"),
        mk("c", "funding_only", industry="healthcare", city="Boulder", state="CO", freshness="stale", date="2026-06-01"),
        mk("d", "cfo_wanted", industry="fintech", city="Denver", state="CO", freshness="fresh", date="2026-07-04"),
        mk("e", "funding_only", industry="healthcare", city="Miami", state="FL", freshness="fresh", date="2026-07-07"),
    ]


def test_snapshot_matches_fake_scraper_filtering():
    leads = _universe()
    snap = SnapshotScraper(leads, {"healthcare": []})
    fake = FakeScraper(leads)
    queries = [
        {"industry": "healthcare", "city": "Denver", "freshness": "fresh"},
        {"industry": "healthcare", "state": "CO"},
        {"city": "Denver"},
        {"signal_type": "cfo_wanted", "freshness": "fresh"},
        {"state": "co", "exclude_ids": ["a", "b"]},   # state abbrev/normalization
        {"industry": "healthcare", "freshness": "stale"},
    ]
    for q in queries:
        assert [l.id for l in snap.leads(**q)] == [l.id for l in fake.leads(**q)], q


def test_snapshot_sorts_freshest_first_and_limits():
    snap = SnapshotScraper(_universe(), {})
    got = snap.leads(industry="healthcare")
    assert [l.id for l in got] == ["e", "b", "a", "c"]     # by newest signal date desc
    assert [l.id for l in snap.leads(industry="healthcare", limit=2)] == ["e", "b"]


def test_snapshot_niches_no_calls():
    snap = SnapshotScraper([], {"healthcare": ["dental"], "fintech": []})
    assert snap.niches() == {"healthcare": ["dental"], "fintech": []}
