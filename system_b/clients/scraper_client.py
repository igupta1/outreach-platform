"""Thin wrapper over System A's lead inventory API (/api/leads,
/api/niches), with a ~2-minute response cache (spec Part 2).

Query params mirror the live API:
  industry, niche, city, state, signal_type, finance_grade, freshness,
  exclude_ids (comma-joined), limit.

NOTE (field-name reality vs. spec): the live lead object has no top-level
`score` or `finance_grade`, and `date_confidence` is per-signal. The
`finance_grade` query param is accepted by the API but currently a no-op;
we still forward it so it works the day System A adds the field.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from typing import Any

import httpx

from system_b import config
from system_b.models import Lead


class ScraperClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        cache_ttl_s: int | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.base_url = (base_url or config.SCRAPER_BASE_URL).rstrip("/")
        self.cache_ttl_s = cache_ttl_s if cache_ttl_s is not None else config.SCRAPER_CACHE_TTL_S
        self._client = httpx.Client(timeout=timeout_s)
        self._cache: dict[str, tuple[float, Any]] = {}

    # --- cache -------------------------------------------------------------

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit is not None and now - hit[0] < self.cache_ttl_s:
            return hit[1]
        resp = self._client.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        data = resp.json()
        self._cache[key] = (now, data)
        return data

    # --- endpoints ---------------------------------------------------------

    def niches(self) -> dict[str, list[str]]:
        """The two-level taxonomy: {parent: [child, ...]}."""
        data = self._get_json("/api/niches", {})
        return dict(data.get("taxonomy") or {})

    def leads(
        self,
        *,
        industry: str | None = None,
        niche: str | None = None,
        city: str | None = None,
        state: str | None = None,
        signal_type: str | None = None,
        finance_grade: str | None = None,
        freshness: str | None = None,
        exclude_ids: Sequence[str] | Iterable[str] | None = None,
        limit: int | None = None,
    ) -> list[Lead]:
        params: dict[str, Any] = {}
        if industry:
            params["industry"] = industry
        if niche:
            params["niche"] = niche
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if signal_type:
            params["signal_type"] = signal_type
        if finance_grade:
            params["finance_grade"] = finance_grade
        if freshness:
            params["freshness"] = freshness
        if exclude_ids:
            ids = [str(x) for x in exclude_ids if x]
            if ids:
                params["exclude_ids"] = ",".join(ids)
        if limit is not None:
            params["limit"] = int(limit)

        data = self._get_json("/api/leads", params)
        return [Lead.model_validate(l) for l in (data.get("leads") or [])]

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ScraperClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
