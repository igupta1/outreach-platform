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

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import httpx

from system_b import config
from system_b.models import Lead

log = logging.getLogger("system_b.scraper")


def _ensure_file_logging() -> None:
    """Persist scraper failures to system_b/logs/scraper.log (append). Best
    effort — never let logging setup break the client."""
    if any(isinstance(h, logging.FileHandler) for h in log.handlers):
        return
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "scraper.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    except OSError:
        pass


def _is_retryable(exc: httpx.HTTPError) -> bool:
    """Retry transient failures: 5xx responses and connection/timeout errors.
    4xx (client errors) are permanent — do not retry."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.RequestError)


def _describe(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


class ScraperClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        cache_ttl_s: int | None = None,
        timeout_s: float = 15.0,
        max_attempts: int = 3,
        backoff_base_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = (base_url or config.SCRAPER_BASE_URL).rstrip("/")
        self.cache_ttl_s = cache_ttl_s if cache_ttl_s is not None else config.SCRAPER_CACHE_TTL_S
        self.max_attempts = max(1, max_attempts)
        self.backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._client = httpx.Client(timeout=timeout_s)
        self._cache: dict[str, tuple[float, Any]] = {}
        _ensure_file_logging()

    # --- request (retry + cache) ------------------------------------------

    def _request_json(self, url: str, params: dict[str, Any]) -> Any:
        """GET with retry-and-exponential-backoff on transient failures.
        Every failed attempt is logged; the final failure re-raises."""
        for attempt in range(self.max_attempts):
            try:
                resp = self._client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as exc:
                last = attempt == self.max_attempts - 1
                if not _is_retryable(exc) or last:
                    log.error(
                        "scraper GET failed (%s) url=%s params=%s attempt=%d/%d",
                        _describe(exc), url, params, attempt + 1, self.max_attempts,
                    )
                    raise
                delay = self.backoff_base_s * (2 ** attempt)
                log.warning(
                    "scraper GET retryable (%s) url=%s params=%s attempt=%d/%d; retrying in %.1fs",
                    _describe(exc), url, params, attempt + 1, self.max_attempts, delay,
                )
                self._sleep(delay)
        raise RuntimeError("unreachable")  # loop always returns or raises

    def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        key = path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit is not None and now - hit[0] < self.cache_ttl_s:
            return hit[1]
        data = self._request_json(f"{self.base_url}{path}", params)
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


class SnapshotScraper:
    """Pulls the WHOLE lead inventory once, then answers .leads(**params)
    from memory using the exact same filter/sort as the live API. For batch
    runs: System A gets 2 calls total (taxonomy + all leads) instead of
    ~10 per prospect, so it can't be overwhelmed mid-batch.

    Same interface as ScraperClient (niches / leads / context manager), so
    build_gift() can't tell the difference.
    """

    def __init__(self, leads: list[Lead], taxonomy: dict[str, list[str]]) -> None:
        self._all = leads
        self._taxonomy = taxonomy

    @classmethod
    def fetch(cls, base_url: str | None = None, *, limit: int = 100_000, **client_kw: Any) -> "SnapshotScraper":
        """Build a snapshot from the live API (one taxonomy + one leads call)."""
        client = ScraperClient(base_url, **client_kw)
        try:
            taxonomy = client.niches()
            all_leads = client.leads(limit=limit)   # no filters, both freshnesses
            log.info("snapshot: %d leads, %d taxonomy parents", len(all_leads), len(taxonomy))
            return cls(all_leads, taxonomy)
        finally:
            client.close()

    @classmethod
    def from_inventory_file(cls, path: str, taxonomy: dict[str, list[str]]) -> "SnapshotScraper":
        """Build a snapshot from a locally-generated inventory.json (same lead
        shape as /api/leads). Taxonomy is passed in (it isn't in the file)."""
        import json
        from pathlib import Path as _Path

        data = json.loads(_Path(path).read_text())
        leads = [Lead.model_validate(row) for row in (data.get("leads") or [])]
        log.info("snapshot(file): %d leads from %s", len(leads), path)
        return cls(leads, taxonomy)

    def niches(self) -> dict[str, list[str]]:
        return self._taxonomy

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
        # Lazy import avoids a client<->engine import cycle at module load.
        from system_b.gift.engine import norm_loc, norm_state

        excluded = {str(x) for x in (exclude_ids or []) if x}
        out: list[Lead] = []
        for l in self._all:
            if l.id in excluded:
                continue
            if industry and l.industry != industry:
                continue
            if niche and l.niche != niche:
                continue
            if city and norm_loc(l.city) != norm_loc(city):
                continue
            if state and norm_state(l.state) != norm_state(state):
                continue
            if signal_type and l.signal_type != signal_type:
                continue
            if finance_grade and l.finance_grade != finance_grade:
                continue
            if freshness and l.freshness != freshness:
                continue
            out.append(l)
        out.sort(key=lambda l: l.newest_date, reverse=True)   # freshest-first
        if limit:
            out = out[:limit]
        return out

    def close(self) -> None:
        pass

    def __enter__(self) -> "SnapshotScraper":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
