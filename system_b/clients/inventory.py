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
from collections import Counter
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


# Tokens that stay uppercase when a SHOUTING name is calmed down. Legal forms
# and country codes read wrong title-cased ("Adfac, Llc"), and a 1-2 letter
# token is almost never a word ("GP INSTALLATION" -> "GP Installation").
# Note which legal forms are NOT here: Inc., Corp., Ltd. and Co. are
# conventionally title-cased, so "UPSIDEHOM, INC." should read "Upsidehom, Inc."
# while "ADFAC, LLC" keeps its LLC.
_KEEP_UPPER = frozenset({
    "llc", "llp", "lp", "pc", "pllc",
    "usa", "us", "uk", "dba", "cpa", "it", "hr", "ai", "tv", "pr", "hvac",
})
_ALPHA_RE = re.compile(r"[A-Za-z]")


def _decap_token(token: str) -> str:
    core = "".join(ch for ch in token if ch.isalnum())
    if len(core) <= 2 or core.lower() in _KEEP_UPPER:
        return token                     # "GP", "LLC", "US" — leave them alone
    return token[:1] + token[1:].lower()


def _fix_shouting(name: str) -> str:
    """`DEPENDABLE SERVICE PLUMBING & AIR` -> `Dependable Service Plumbing & Air`.

    An ALL-CAPS name shouts inside otherwise-lowercase prose and reads as
    scraped. Applied ONLY when the whole name is uppercase, so a name that
    chose its own mixed casing ("F3EA Inc", "co:census") is untouched.

    A single short token is left alone: `NACDD` and `MAPS` are acronyms, and
    "Nacdd" would be the same mangling this is meant to prevent. Multi-word
    names are safe to calm down — an all-caps phrase is styling, not an
    acronym."""
    if not _ALPHA_RE.search(name) or name != name.upper():
        return name
    tokens = name.split()
    if len(tokens) == 1 and len(tokens[0]) <= 6:
        return name                      # NACDD, MAPS, SISU — acronym, not shouting
    return " ".join(_decap_token(t) for t in tokens)


def _clean_company_name(name: str) -> str:
    """Tidy raw leadgen company names that get listed verbatim in the email —
    drop a trailing state-registration marker ("... / DE /"), stray separators,
    doubled whitespace, and ALL-CAPS shouting. Conservative: only removes clear
    artifacts, never guesses at truncated names."""
    name = _REG_ARTIFACT_RE.sub("", name)
    name = name.replace(" / ", " ").strip(" /|-")
    name = _MULTISPACE_RE.sub(" ", name).strip()
    return _fix_shouting(name)


# Part-time words safe to print in front of a role. leadgen matches a WIDER set
# (contract, consultant, consulting, advisory, temp, virtual, outsourced) to tag
# a posting fractional, but most of those appear incidentally in ordinary job
# copy — "contract negotiation", "advisory board", "consulting engagements" —
# and reading one of those as the role's nature would put a wrong word in a sent
# email. These three are effectively never incidental, and they read naturally
# as an adjective. Ordered by preference when a posting uses more than one.
_SAFE_QUALIFIERS = ("fractional", "interim", "part-time")
_QUALIFIER_RES = tuple(
    (q, re.compile(r"\b" + q.replace("-", r"[\s-]") + r"\b", re.IGNORECASE))
    for q in _SAFE_QUALIFIERS
)


def _fractional_qualifier(row: dict[str, Any]) -> str | None:
    """The part-time word to prefix onto the role, or None to leave it alone.

    leadgen tags a posting `job_fractional_cfo` when the qualifier appears in the
    title OR the description, but the email prints the TITLE — so a posting whose
    body says "this is a fractional role" renders as a plain "chief financial
    officer" under a subject line promising a fractional one. That gap hit 17 of
    23 emails in a real run.

    Returns None when the title already says it (nothing to add) or when only a
    lower-confidence word appears (we would rather say less than say it wrong)."""
    for sig in row.get("signals") or []:
        if sig.get("type") != "job_fractional_cfo":
            continue
        payload = sig.get("payload") or {}
        title = str(payload.get("title") or sig.get("evidence_text") or "")
        if any(rx.search(title) for _q, rx in _QUALIFIER_RES):
            return None                      # already visible in the printed role
        description = str(payload.get("description") or "")
        for qualifier, rx in _QUALIFIER_RES:
            if rx.search(description):
                return qualifier
    return None


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
        headcount=row.get("headcount"),
        headcount_band=row.get("headcount_band"),
        role_qualifier=_fractional_qualifier(row),
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


def _is_expired_job_lead(lead: Lead, today: date) -> bool:
    """True for a job-posting lead whose posting is old enough that "is looking
    for a {role}" can no longer be trusted. Non-job signals (a breach) describe
    an event that stays true, so the cap does not apply to them."""
    if not (lead.signal_type or "").startswith("job_"):
        return False
    dates = [s.date for s in lead.signals if s.date]
    if not dates:
        return True          # undated job posting: cannot show it is still open
    try:
        newest = max(date.fromisoformat(str(d)[:10]) for d in dates)
    except ValueError:
        return True
    return (today - newest).days > config.MAX_JOB_LEAD_AGE_DAYS


# --- Unusable-lead gate ----------------------------------------------------
#
# A lead that can never make an honest gift line, dropped at load so no gift is
# ever built from it. This is the cheap half of the quality story: it judges a
# lead on its own, with no gift context. Checks that depend on the OTHER leads
# in a gift (a duplicate company, a geo claim) belong in `gift/`, not here.
#
# Every rule drops a lead rather than repairing it, and the inventory has the
# depth to absorb that (hundreds of leads per niche against ~100 prospects), so
# a rejection costs a swap, never a gift.

# An ingest artifact from the fractional board: company names there are rebuilt
# from URL slugs, and a slug carrying a content hash leaves it welded onto the
# name ("Lifesitenews 07Cfc", "Plutus Health Ddb8F"). Deliberately narrow — the
# token must be SPACE-separated, hex-only, AND mix digits with letters. That is
# what separates a hash from the many real brands that end in something similar:
# "Love146" / "Horizon3" / "Imagine360" are attached (no space), and "Studio 54"
# / "Area 51" are digits-only. Both survive; only the hash shape is caught.
_ID_SUFFIX_RE = re.compile(r"\s[0-9A-Fa-f]{4,8}$")


def _has_id_suffix(name: str) -> bool:
    m = _ID_SUFFIX_RE.search(name or "")
    if m is None:
        return False
    token = m.group(0).strip()
    return any(c.isdigit() for c in token) and any(c.isalpha() for c in token)


# A job board's description often opens by naming the company that is actually
# hiring. When that is a DIFFERENT company from the lead, the posting was placed
# by a recruiter or agency on someone else's behalf, and the email would credit
# the wrong company with the role — the one error a recipient can catch outright.
_HIRER_RE = re.compile(
    r"^\s*(?:About the role|About us|Position Summary|Position Overview|Job Summary)?\s*"
    r"([A-Z][\w&.,'-]*(?:\s+[A-Z][\w&.,'-]*){0,4})\s+is\s+(?:looking for|seeking|hiring)",
)
# Openers that name no one in particular — not evidence of a different hirer.
_GENERIC_HIRER_RE = re.compile(
    r"^(?:our|the|a|an|this|we|us|company|client|organization|team|employer)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9]+")
# Tokens shared by unrelated company names; overlap on these proves nothing.
_STOP_TOKENS = frozenset({
    "inc", "llc", "ltd", "corp", "co", "company", "group", "holdings", "the",
    "and", "of", "services", "solutions", "partners", "associates", "systems",
    "technologies", "international", "global", "usa", "america",
})


def _name_tokens(name: str) -> set[str]:
    return {w for w in _WORD_RE.findall((name or "").lower()) if w not in _STOP_TOKENS}


def _foreign_hirer(row: dict[str, Any], company: str) -> str | None:
    """The company a posting's own body says is hiring, when that is clearly not
    this lead. None when the body names nobody, names this company, or is absent."""
    own = _name_tokens(company)
    if not own:
        return None
    for sig in row.get("signals") or []:
        desc = ((sig.get("payload") or {}).get("description") or "").strip()
        if not desc:
            continue
        m = _HIRER_RE.match(desc)
        if m is None:
            continue
        claimed = m.group(1).strip()
        if _GENERIC_HIRER_RE.match(claimed):
            continue
        if _name_tokens(claimed) & own:
            continue          # same company, phrased differently
        return claimed
    return None


def _unusable_reason(row: dict[str, Any], lead: Lead) -> str | None:
    """Why this lead can never make an honest gift line, or None when it can."""
    if _has_id_suffix(lead.company):
        return "id_suffixed_name"
    # A domainless lead is NOT dropped here. `gift.engine.sort_key` already
    # ranks it below every resolvable company, which keeps it out of gifts that
    # have better options while still leaving it available when a narrow
    # prospect's pool is thin. Dropping it would make that tiebreak dead code
    # and cost real leads (154 in accounting, 39 in cfo) for a case the ranking
    # already handles.
    foreign = _foreign_hirer(row, lead.company)
    if foreign is not None:
        return f"posting_hires_for={foreign!r}"
    return None


def _adapt_rows(rows: list[dict[str, Any]], *, today: date) -> list[Lead]:
    kept: list[Lead] = []
    expired = 0
    unusable: Counter[str] = Counter()
    for row in rows:
        lead = adapt_leadgen_lead(row, today=today)
        if _is_expired_job_lead(lead, today):
            expired += 1
            continue
        reason = _unusable_reason(row, lead)
        if reason is not None:
            unusable[reason.split("=")[0]] += 1
            log.debug("inventory: dropped %s — %s", lead.company, reason)
            continue
        kept.append(lead)
    if expired:
        log.info("inventory: dropped %d job lead(s) older than %d days",
                 expired, config.MAX_JOB_LEAD_AGE_DAYS)
    if unusable:
        log.info("inventory: dropped %d unusable lead(s): %s",
                 sum(unusable.values()), dict(unusable.most_common()))
    return kept


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
