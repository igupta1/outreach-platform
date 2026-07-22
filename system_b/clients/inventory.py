"""Unified lead-inventory client.

The lead platform was rebuilt as `leadgen`: it emits ONE JSON inventory per
niche (a `<niche>-leads.json` with a new row shape), replacing the old
per-niche adapters (`adapt_it_lead`, `adapt_bookkeeping_lead`) and the old
`/api/generate-leads` + `/api/niche-leads` wiring.

This module is the single place that adapts a leadgen row onto the outreach
`Lead` and serves it through the existing `.leads(**params)` interface (via
`SnapshotScraper`), so `gift.engine.build_gift` works unchanged.

Two read modes:
  * Stub  — env `LEADGEN_INVENTORY_DIR` set: read the on-disk inventory file.
  * Live  — else GET `{SCRAPER_BASE_URL}/api/niche-inventory?niche=<key>`
            (this website endpoint is PENDING; the call is implemented and it
            is fine that it 404s until the website pass adds it).

Dependency-light: reuses `SnapshotScraper` / `ScraperClient` from
`scraper_client` (so the live path inherits its retry+backoff+cache
resilience); `httpx` is only pulled in transitively via that client.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from system_b import config
from system_b.clients.scraper_client import ScraperClient, SnapshotScraper
from system_b.models import Lead, Signal

log = logging.getLogger("system_b.inventory")

# The five leadgen niches. `niche_key` must be one of these.
VALID_NICHES: frozenset[str] = frozenset(
    {"accounting", "cfo", "mssp", "msp", "cloud"}
)

_NONWORD_RE = re.compile(r"[^a-z0-9]+")

# Niche-neutral fallback line for a lead that carries no per-signal evidence.
_DEFAULT_DESCRIPTION = "just showed a buying signal"


def _freshness(event_date: str | None, today: date) -> str:
    """`fresh` iff `event_date` is within FRESH_WINDOW_DAYS of `today`, else
    `stale`. Unparseable / missing / future-out-of-window dates are `stale`."""
    try:
        d = date.fromisoformat((event_date or "")[:10])
    except (ValueError, TypeError):
        return "stale"
    delta = (today - d).days
    return "fresh" if 0 <= delta <= config.FRESH_WINDOW_DAYS else "stale"


def _synthesize_id(niche: str | None, company: str, state: str | None) -> str:
    """Stable id from niche+company+state (used only when the leadgen row has
    no `id`)."""
    slug = _NONWORD_RE.sub("-", f"{niche or ''} {company} {state or ''}".lower()).strip("-")
    return f"leadgen:{slug}"


def _primary_signal(row: dict[str, Any]) -> dict[str, Any]:
    """The first leadgen signal on the row (drives freshness). Empty dict when
    the row carries no signals."""
    signals = row.get("signals") or []
    return signals[0] if signals else {}


def adapt_leadgen_lead(row: dict[str, Any], *, today: date) -> Lead:
    """Map one leadgen inventory row onto the outreach `Lead` shape.

    Field mapping:
      company     <- row["name"]
      value_prop  <- row.get("insight")
      signal_type <- row["signal_type"]            (leadgen raw type, kept verbatim)
      domain / city / state / industry             passthrough
      niche       <- row.get("niche")              (may be None)
      freshness   <- fresh|stale from the PRIMARY signal's event_date vs today
      id          <- row["id"] if present, else synthesized niche+company+state
      signals     <- each leadgen signal ->
                       Signal(type=s["type"], date=s.get("event_date"),
                              date_confidence="high",
                              plain_words_description=s.get("evidence_text"))
    """
    company = row.get("name") or ""
    niche = row.get("niche")

    primary = _primary_signal(row)
    freshness = _freshness(primary.get("event_date"), today)

    signals = [
        Signal(
            type=s.get("type"),
            date=s.get("event_date"),
            date_confidence="high",
            plain_words_description=s.get("evidence_text"),
        )
        for s in (row.get("signals") or [])
    ]

    lead_id = row.get("id") or _synthesize_id(niche, company, row.get("state"))

    return Lead(
        id=str(lead_id),
        company=company,
        domain=row.get("domain"),
        city=row.get("city"),
        state=row.get("state"),
        industry=row.get("industry"),
        niche=niche,
        value_prop=row.get("insight"),
        signal_type=row["signal_type"],
        freshness=freshness,
        signals=signals,
    )


def _validate_niche(niche_key: str) -> None:
    if niche_key not in VALID_NICHES:
        raise ValueError(
            f"unknown niche_key {niche_key!r}; expected one of "
            f"{sorted(VALID_NICHES)}"
        )


def load_taxonomy() -> dict[str, list[str]]:
    """The shared vertical taxonomy (parent -> children) the research/Gate-B
    matching classifies into. Stub: `<LEADGEN_INVENTORY_DIR>/taxonomy.json`;
    live: `{SCRAPER_BASE_URL}/api/niches`. Empty dict if unavailable."""
    inventory_dir = os.environ.get("LEADGEN_INVENTORY_DIR")
    if inventory_dir:
        path = Path(inventory_dir) / "taxonomy.json"
        if path.exists():
            return dict((json.loads(path.read_text()) or {}).get("taxonomy") or {})
        return {}
    client = ScraperClient()
    try:
        data = client._get_json("/api/niches", {})
    except Exception:  # noqa: BLE001 — taxonomy is best-effort
        return {}
    finally:
        client.close()
    return dict((data or {}).get("taxonomy") or {})


def _adapt_rows(rows: list[dict[str, Any]], *, today: date) -> list[Lead]:
    return [adapt_leadgen_lead(row, today=today) for row in rows]


def snapshot_for_niche(
    niche_key: str, *, today: date | None = None
) -> SnapshotScraper:
    """Return a `SnapshotScraper` over one niche's adapted leadgen inventory.

    Stub mode (default) — if env `LEADGEN_INVENTORY_DIR` is set, read
    `<LEADGEN_INVENTORY_DIR>/<niche_key>-leads.json` off disk.

    Live mode — else GET `{SCRAPER_BASE_URL}/api/niche-inventory?niche=<key>`
    (PENDING endpoint) via `ScraperClient`, inheriting its retry/backoff/cache.

    Raises ValueError if `niche_key` is not a known niche.
    """
    _validate_niche(niche_key)
    today = today or date.today()

    inventory_dir = os.environ.get("LEADGEN_INVENTORY_DIR")
    if inventory_dir:
        path = Path(inventory_dir) / f"{niche_key}-leads.json"
        data = json.loads(path.read_text())
        rows = data.get("leads") or []
        leads = _adapt_rows(rows, today=today)
        log.info("inventory(stub): %d leads for niche=%s from %s", len(leads), niche_key, path)
        return SnapshotScraper(leads, taxonomy=load_taxonomy())

    # Live mode: reuse ScraperClient so the call gets the same resilience
    # (retry + exponential backoff + response cache) as the rest of System B.
    client = ScraperClient()
    try:
        data = client._get_json("/api/niche-inventory", {"niche": niche_key})
    finally:
        client.close()
    rows = (data or {}).get("leads") or []
    leads = _adapt_rows(rows, today=today)
    log.info("inventory(live): %d leads for niche=%s", len(leads), niche_key)
    return SnapshotScraper(leads, taxonomy=load_taxonomy())


def descriptions_for(leads: list[Lead]) -> dict[str, str]:
    """{lead.id: its signals[0].plain_words_description or a niche-neutral
    fallback}. Mirrors the old `it_descriptions` / `bookkeeping_descriptions`
    so callers that want a static per-lead line have one."""
    out: dict[str, str] = {}
    for lead in leads:
        out[lead.id] = next(
            (s.plain_words_description for s in lead.signals if s.plain_words_description),
            _DEFAULT_DESCRIPTION,
        )
    return out
