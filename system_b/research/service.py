"""Orchestration: fetch a prospect's site and classify it. Network lives here so
the classifier stays pure and fully testable.

2026-11-13 (the user: "reduce our api usage without sacrificing quality"):
a firm's research is kept for CACHE_DAYS. The nightly run reads every unsent
prospect (about 900) to put industry matches first, and used to fetch and
classify all of them again every night to draft 200. The same site gives the
same answer, so it is asked once a month. `CACHE_VERSION` is part of the key:
bump it when the research code changes what it returns, and every firm is
read fresh. A site that could not be fetched is never kept.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from system_b.research.classifier import LlmFn, classify
from system_b.research.fetcher import fetch_site
from system_b.research.llm import classify_site, client_names_fit
from system_b.research.models import Evidence, ResearchResult

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "research-cache.json"
CACHE_DAYS = 30
CACHE_VERSION = "2026-11-13"
_cache: dict | None = None


def _key(website: str) -> str:
    w = (website or "").strip().lower().split("//", 1)[-1].removeprefix("www.").rstrip("/")
    return f"{CACHE_VERSION}|{w}"


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _from_dict(d: dict) -> ResearchResult:
    d = dict(d)
    d["evidence"] = [Evidence(**e) for e in d.get("evidence") or []]
    for k in ("match_param", "client_revenue"):
        if d.get(k) is not None:
            d[k] = tuple(d[k])
    d["candidate_match_params"] = [tuple(m) for m in d.get("candidate_match_params") or []]
    return ResearchResult(**d)


def cached(website: str, today: date | None = None) -> ResearchResult | None:
    row = _load().get(_key(website))
    if not row:
        return None
    today = today or date.today()
    try:
        if date.fromisoformat(row["on"]) < today - timedelta(days=CACHE_DAYS):
            return None
        return _from_dict(row["result"])
    except (KeyError, TypeError, ValueError):
        return None


def keep(website: str, result: ResearchResult, today: date | None = None) -> None:
    _load()[_key(website)] = {"on": (today or date.today()).isoformat(), "result": asdict(result)}


def flush() -> None:
    if _cache is None:
        return
    try:
        with CACHE_PATH.open("w", encoding="utf-8") as fh:   # in place: may be a symlink
            json.dump(_cache, fh)
    except OSError:
        pass


def research_prospect(
    website: str,
    taxonomy: dict[str, list[str]],
    *,
    llm: LlmFn | None = None,
) -> ResearchResult:
    """Fetch + classify one prospect's website. `llm` defaults to OpenAI;
    inject a fake in tests (a fake is never cached). The client-list check
    (`client_names_fit`) runs only with the real classifier, so a test's fake
    never reaches the network."""
    if llm is None and (hit := cached(website)) is not None:
        return hit
    site = fetch_site(website)
    result = classify(site, taxonomy, llm=llm or classify_site,
                      client_fit=client_names_fit if llm is None else None)
    if llm is None and site:
        keep(website, result)
    return result
