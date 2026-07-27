"""Unified lead-inventory client.

The lead platform was rebuilt as `leadgen`: it emits ONE JSON inventory per
niche (a `<niche>-leads.json` with a new row shape), replacing the old
per-niche adapters (`adapt_it_lead`, `adapt_bookkeeping_lead`) and the old
`/api/generate-leads` + `/api/niche-leads` wiring.

This module is the single place that adapts a leadgen row onto the outreach
`Lead` and serves it through the existing `.leads(**params)` interface (via
`SnapshotScraper`), so `gift.engine.build_gift` works unchanged.

Two read modes (blob wins so a leftover local dir can't pin stale gifts):
  * Blob  — env `LEADGEN_BLOB_BASE_URL` set: GET `<base>/<niche>-leads.json`
            straight from the lead platform's public Vercel Blob (no auth, no
            website). This is the daily-fresh path.
  * Local — else env `LEADGEN_INVENTORY_DIR` set: read the on-disk file
            (offline fallback / dev).

Either way a freshness guard refuses to generate against inventory older than
`LEADGEN_MAX_INVENTORY_AGE_DAYS` (default 3) unless `LEADGEN_ALLOW_STALE=1`, so
a broken daily refresh can't silently produce week-old gifts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from system_b import config
from system_b.clients.scraper_client import SnapshotScraper
from system_b.models import Lead, Signal

log = logging.getLogger("system_b.inventory")

# The five leadgen niches. `niche_key` must be one of these.
VALID_NICHES: frozenset[str] = frozenset(
    {"accounting", "cfo", "mssp", "msp", "cloud"}
)

_NONWORD_RE = re.compile(r"[^a-z0-9]+")

# Niche-neutral fallback line for a lead that carries no per-signal evidence.
_DEFAULT_DESCRIPTION = "just showed a buying signal"


# --- Inventory source config (read at call time so tests can monkeypatch) ---


class StaleInventoryError(RuntimeError):
    """The pulled inventory is older than the freshness limit and
    LEADGEN_ALLOW_STALE is not set — the daily refresh is probably broken."""


def _blob_base() -> str:
    return os.environ.get("LEADGEN_BLOB_BASE_URL", "").rstrip("/")


def _max_inventory_age_days() -> int:
    try:
        return int(os.environ.get("LEADGEN_MAX_INVENTORY_AGE_DAYS", "3"))
    except ValueError:
        return 3


def _allow_stale() -> bool:
    return bool(os.environ.get("LEADGEN_ALLOW_STALE"))


def _fetch_blob_json(name: str) -> dict[str, Any]:
    """GET one published JSON file from the public Vercel Blob base. Public
    reads need no auth; small retry rides out a transient CDN/network blip."""
    url = f"{_blob_base()}/{name}"
    last: Exception | None = None
    for attempt in range(3):
        try:
            resp = httpx.get(url, timeout=20.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            last = exc
            log.warning("blob fetch %s failed (attempt %d/3): %s", name, attempt + 1, exc)
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def _check_freshness(data: dict[str, Any], niche_key: str, today: date) -> None:
    """Refuse (or, with LEADGEN_ALLOW_STALE, warn) if the inventory's
    `generated_at` is older than the freshness limit. Missing generated_at is
    a warning only — an offline hand-made file has no date."""
    gen = data.get("generated_at")
    try:
        gen_date = date.fromisoformat(str(gen)[:10]) if gen else None
    except ValueError:
        gen_date = None
    if gen_date is None:
        log.warning("inventory(%s): no generated_at — cannot verify freshness", niche_key)
        return
    age = (today - gen_date).days
    if age <= _max_inventory_age_days():
        return
    msg = (
        f"{niche_key} inventory is {age} days old (generated {gen_date}); the daily "
        f"leadgen refresh may be broken. Refresh it, or set LEADGEN_ALLOW_STALE=1 "
        f"to generate against stale gifts anyway."
    )
    if _allow_stale():
        log.warning("%s [proceeding: LEADGEN_ALLOW_STALE]", msg)
    else:
        raise StaleInventoryError(msg)


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


_REG_ARTIFACT_RE = re.compile(r"\s*/\s*[A-Za-z]{2}\s*/\s*$")   # "Intermezzo Inc. / DE /"
_MULTISPACE_RE = re.compile(r"\s{2,}")


def _clean_company_name(name: str) -> str:
    """Tidy raw leadgen company names that get listed verbatim in the email —
    drop a trailing state-registration marker ("... / DE /"), stray separators,
    and doubled whitespace. Conservative: only removes clear artifacts, never
    guesses at truncated or oddly-cased names."""
    name = _REG_ARTIFACT_RE.sub("", name)
    name = name.replace(" / ", " ").strip(" /|-")
    return _MULTISPACE_RE.sub(" ", name).strip()


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
                              plain_words_description=s.get("evidence_text"),
                              source_url=s.get("source_url"))
    """
    company = _clean_company_name(row.get("name") or "")
    niche = row.get("niche")

    primary = _primary_signal(row)
    freshness = _freshness(primary.get("event_date"), today)

    signals = [
        Signal(
            type=s.get("type"),
            date=s.get("event_date"),
            date_confidence="high",
            plain_words_description=s.get("evidence_text"),
            source_url=s.get("source_url"),
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
    matching classifies into. Blob: `<LEADGEN_BLOB_BASE_URL>/taxonomy.json`;
    else local: `<LEADGEN_INVENTORY_DIR>/taxonomy.json`. Empty dict if
    unavailable (taxonomy is best-effort — the pipeline degrades, not breaks)."""
    if _blob_base():
        try:
            data = _fetch_blob_json("taxonomy.json")
            return dict((data or {}).get("taxonomy") or {})
        except Exception:  # noqa: BLE001 — taxonomy is best-effort
            log.warning("blob taxonomy fetch failed — continuing without it", exc_info=True)
            return {}
    inventory_dir = os.environ.get("LEADGEN_INVENTORY_DIR")
    if inventory_dir:
        path = Path(inventory_dir) / "taxonomy.json"
        if path.exists():
            return dict((json.loads(path.read_text()) or {}).get("taxonomy") or {})
    return {}


def _adapt_rows(rows: list[dict[str, Any]], *, today: date) -> list[Lead]:
    return [adapt_leadgen_lead(row, today=today) for row in rows]


def snapshot_for_niche(
    niche_key: str, *, today: date | None = None
) -> SnapshotScraper:
    """Return a `SnapshotScraper` over one niche's adapted leadgen inventory.

    Blob mode (primary) — if `LEADGEN_BLOB_BASE_URL` is set, GET
    `<base>/<niche_key>-leads.json` from the public Vercel Blob (no auth).

    Local mode (fallback) — else if `LEADGEN_INVENTORY_DIR` is set, read
    `<dir>/<niche_key>-leads.json` off disk.

    Either way the freshness guard runs (see `_check_freshness`). Raises
    ValueError for an unknown niche, StaleInventoryError if too old, and
    RuntimeError if no source is configured.
    """
    _validate_niche(niche_key)
    today = today or date.today()

    if _blob_base():
        data = _fetch_blob_json(f"{niche_key}-leads.json")
        _check_freshness(data, niche_key, today)
        rows = data.get("leads") or []
        leads = _adapt_rows(rows, today=today)
        log.info("inventory(blob): %d leads for niche=%s from %s",
                 len(leads), niche_key, _blob_base())
        return SnapshotScraper(leads, taxonomy=load_taxonomy())

    inventory_dir = os.environ.get("LEADGEN_INVENTORY_DIR")
    if inventory_dir:
        path = Path(inventory_dir) / f"{niche_key}-leads.json"
        data = json.loads(path.read_text())
        _check_freshness(data, niche_key, today)
        rows = data.get("leads") or []
        leads = _adapt_rows(rows, today=today)
        log.info("inventory(local): %d leads for niche=%s from %s", len(leads), niche_key, path)
        return SnapshotScraper(leads, taxonomy=load_taxonomy())

    raise RuntimeError(
        "no lead inventory configured: set LEADGEN_BLOB_BASE_URL (daily Vercel "
        "Blob) or LEADGEN_INVENTORY_DIR (offline folder)."
    )


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
