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
from system_b.clients.people import looks_like_person
from system_b.clients.scraper_client import SnapshotScraper
from system_b.models import Lead, Signal

log = logging.getLogger("system_b.inventory")

# The six leadgen niches. `niche_key` must be one of these.
#
# The three finance niches are one ladder split by the rung a company hires at:
# bookkeeping (junior) · accounting (controller) · cfo (fractional CFO). Which
# one a prospect belongs to is the OPERATOR's call, passed as --pack; nothing
# here infers it from a company name.
VALID_NICHES: frozenset[str] = frozenset(
    {"bookkeeping", "accounting", "cfo", "mssp", "msp", "cloud"}
)

# The three FINANCE niches no longer have a job-post inventory: leadgen stopped
# emitting them on 2026-09-08 (see leadgen/niches/__init__.py) because job
# posts are the wrong gift — a company advertising an in-house bookkeeper has
# decided AGAINST outsourcing, and "Fractional CFO wanted" is on every board.
#
# The old JSON is still sitting on the blob and will never be refreshed again,
# so `--legacy-niche --pack cfo` would silently build a gift from months-old
# job posts. That is the one way to accidentally send the retired system's
# output, so it is refused rather than left as a footgun. The IT packs still
# use this path and are unaffected.
RETIRED_JOB_NICHES: frozenset[str] = frozenset({"bookkeeping", "accounting", "cfo"})

_NONWORD_RE = re.compile(r"[^a-z0-9]+")

LOCAL_TAXONOMY = Path(__file__).resolve().parent.parent / "data" / "taxonomy.json"


# --- Inventory source config (read at call time so tests can monkeypatch) ---


class StaleInventoryError(RuntimeError):
    """The pulled inventory is older than the freshness limit and
    LEADGEN_ALLOW_STALE is not set — the daily refresh is probably broken."""


def _blob_base() -> str:
    return os.environ.get("LEADGEN_BLOB_BASE_URL", "").rstrip("/")


# How long each magnet may go without a refresh before the run complains.
#
# The old rule was a single 3-day limit for every source, which was correct
# when one nightly cron rebuilt everything. The magnets now come out of ONE
# place -- the lead inventory (~/Developer/Inventory), refreshed BY HAND for
# the MVP (`leadinv.run refresh`, then `publish`) -- so each file gets the same
# 45 days: a missed fortnight still runs, a forgotten month and a half stops
# the batch. A file's `generated_at` is its SOURCE's emit date, so a fresh
# publish of old data still reads as old. Per-lead expiry is separate: every
# contract-v2 lead carries its own `expires_at` (see `_past_expiry`).
#
# The older magnets (funds, ecommerce) are switched off upstream; their limits
# stay so `LEADGEN_INVENTORY_DIR` pointed at an old folder still reads them.
MAGNET_MAX_AGE_DAYS: dict[str, int] = {
    "nonprofit": 45,
    "construction": 45,
    "govcon": 45,
    "grant": 45,
    "newbusiness": 45,
    # The legal-duty families (2026-10-27). The inventory refreshes every
    # source weekly (Inventory ops/refresh.sh, Wednesdays), so each limit is
    # its source's own cadence plus one missed run: a weekly list goes stale
    # after three weeks, DOL's monthly Form 5500 snapshot and the 990 scan
    # after 45 days, and TTB's new-permit file (7 days, then overwritten)
    # after two weeks.
    "nonprofitduty": 45,
    "benefits": 45,
    "taxtrouble": 21,
    "healthcare": 30,
    "property": 30,
    "securities": 21,
    "publicsector": 30,
    "specialty": 14,
    "constructionduty": 21,
    "govconduty": 30,
    "funds": 75,          # SEC publishes monthly (off upstream)
    "ecommerce": 180,     # refreshed when a new Apollo export is bought (off upstream)
}

DEFAULT_MAX_AGE_DAYS = 3          # the old job-post inventory: a nightly cron


def _max_inventory_age_days(key: str | None = None) -> int:
    override = os.environ.get("LEADGEN_MAX_INVENTORY_AGE_DAYS")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return MAGNET_MAX_AGE_DAYS.get(key or "", DEFAULT_MAX_AGE_DAYS)


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
    if age <= _max_inventory_age_days(niche_key):
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
_AKA_RE = re.compile(r"\s+(?:a/k/a|aka|f/k/a|fka)\s+", re.IGNORECASE)


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


# --- title-cased names: acronyms and registry abbreviations -----------------
#
# Most sources title-case what they were given, so an acronym arrives as a
# word ("Wscadv", "Sc Uplift", "Houston Sro Housing") and a registry's
# abbreviation as a non-word ("Comn Action Partnership", "Lndscpg"). Both read
# as scraped in an email. A token is only touched when it is in plain Title
# case (`_fix_token`), so a name that chose its own casing ("iRobot",
# "F3EA Inc") never is.

# Registry abbreviations with ONE obvious reading (the IRS's 990 names and
# Florida's DBPR names). Anything ambiguous ("Mnt": mount or maintenance?) is
# left as the source wrote it.
_EXPAND = {
    "comn": "Community", "cmty": "Community", "assn": "Association",
    "assoc": "Association", "fdn": "Foundation", "fndtn": "Foundation",
    "natl": "National", "intl": "International", "ctr": "Center",
    "svcs": "Services", "srvs": "Services", "srvcs": "Services", "svs": "Services",
    "svc": "Service", "srv": "Service", "mgmt": "Management", "grp": "Group",
    "sltns": "Solutions", "rmdlng": "Remodeling", "rmdl": "Remodel",
    "lndscpg": "Landscaping", "lndscp": "Landscape", "clng": "Cleaning",
    "cnst": "Construction", "const": "Construction", "constr": "Construction",
    "cnstrtion": "Construction", "flrng": "Flooring", "bldrs": "Builders",
    "rpr": "Repair", "rprs": "Repairs", "gnrl": "General",
    "cnsltnts": "Consultants", "hrdscpng": "Hardscaping", "rnvtns": "Renovations",
    "rstrtn": "Restoration", "dsgn": "Design", "cncrt": "Concrete",
    "htg": "Heating", "wndw": "Window", "pwr": "Power", "fncng": "Fencing",
    "outdr": "Outdoor",
}
# Acronyms the letter rules below cannot see: they start with a vowel or read
# like a syllable.
_ACRONYMS = frozenset({"ahec", "hiv", "naacp", "nami", "aarp", "aclu", "uso",
                       "ame", "esl", "sos"})
# Title-cased words and abbreviations that keep their case although a rule
# below would otherwise read them as initials.
_TITLE_WORDS = frozenset({
    "of", "on", "to", "in", "up", "by", "at", "no", "go", "my", "we", "hi", "an",
    "as", "is", "or", "so", "do", "be", "he", "me", "am", "oh", "ox", "de", "la",
    "el", "le", "du", "da", "di", "st", "jr", "sr", "dr", "mr", "ms", "mt", "ft",
    "co", "ed", "re", "ma", "mo", "yo", "us", "it", "ag", "op",
    "ltd", "mrs", "hwy", "pkwy", "blvd", "mfg", "rd", "ln", "bros", "sri", "tsai",
})
_ROMAN_RE = re.compile(r"^(?=[ivx]{2,4}$)x{0,3}(ix|iv|v?i{0,3})$")   # "Ii", "Iii", "Iv"
# Two consonants that can start an English (or a common surname's) word. A
# token starting with any other pair is initials: "Wscadv", "Sro", "Sfa".
_ONSETS = frozenset((
    "bl br ch cl cr dr dw fl fr gl gr gn gh gw kl kn kr kw kh ph pl pr ps pn pt "
    "pf sc sh sk sl sm sn sp sq st sv sw sz th tr ts tw vl wh wr zh zw rh mc ll "
    "ng bj bh dh cz dj"
).split())
_VOWELS = frozenset("aeiouy")
# Two vowels an English word (or a common name) can start with: "Oak", "Aid",
# "Out", "Iowa". A three-letter token starting with any other pair is initials:
# "Aoc Calton" is AOC Calton (SAM.gov shouts it, `_fix_shouting` calms it).
_VOWEL_STARTS = frozenset("ai au ea ee ei eu oa oi oo ou io ia".split())
_TOKEN_RE = re.compile(r"^([^A-Za-z]*)([A-Za-z]+)([^A-Za-z]*)$")
_TITLE_S_RE = re.compile(r"(?<=[a-z])'S\b")          # "Barrett'S" -> "Barrett's"


def _fix_token(token: str) -> str:
    if "-" in token.strip("-"):
        # "Fls-S" -> "FLS-S": each piece of a hyphenated token on its own.
        # Without this the whole token failed `_TOKEN_RE` and kept its case.
        # Pieces under 3 letters are left alone: in a hyphenated brand they
        # are syllables ("Go-Jo", "Bi-Bett", "D-Fi"), not initials.
        return "-".join(_fix_token(part) if len(part) >= 3 else part
                        for part in token.split("-"))
    m = _TOKEN_RE.match(token)
    if not m or "'" in token:
        return token                       # "Me 'Oe": a word, not initials
    lead, core, tail = m.groups()
    if not (core[0].isupper() and core[1:].islower()):
        return token                       # chose its own casing, or prose
    low = core.lower()
    if low in _EXPAND:
        return lead + _EXPAND[low] + tail
    if len(low) == 1 or low in _TITLE_WORDS:
        return token
    upper = lead + core.upper() + tail
    if low in _KEEP_UPPER or low in _ACRONYMS or _ROMAN_RE.match(low):
        return upper                       # "Llc", "Ahec", "Ii"
    if len(low) == 2 or not set(low) & _VOWELS:
        return upper                       # "Sc", "Nw", "Mds", "Pnw"
    if len(low) == 3 and low[0] in "aeiou" and low[1] in "aeiou" and low[:2] not in _VOWEL_STARTS:
        return upper                       # "Aoc", "Aeg"
    if (low[0] not in "aeiou" and low[1] not in _VOWELS and low[:2] not in _ONSETS
            and (len(low) <= 4 or sum(c in _VOWELS for c in low) <= 1)):
        return upper                       # "Wscadv", "Sro", "Sfa"
    return token


def _fix_title_tokens(name: str) -> str:
    """`Sc Uplift` -> `SC Uplift`, `Mds Ii` -> `MDS II`, `Comn Action` ->
    `Community Action`."""
    name = _TITLE_S_RE.sub("'s", name)
    return " ".join(_fix_token(t) for t in name.split(" "))


# Long words a source cuts mid-way ("Golden Triangle Resource Conservati &
# Development Area"). A token that is a strict prefix of one, and not itself a
# word, is FLAGGED for review and never completed: "Conservati" is almost
# certainly "Conservation", but the name is the one fact a recipient checks.
_LONG_WORDS = (
    "conservation", "development", "association", "foundation", "international",
    "community", "communities", "organization", "corporation", "educational",
    "education", "services", "national", "management", "construction",
    "contractors", "technologies", "technology", "solutions", "consulting",
    "restoration", "renovations", "partnership", "administration", "institute",
    "incorporated", "rehabilitation", "environmental", "residential",
    "commercial", "industries", "enterprises", "behavioral", "recreation",
    "cooperative", "neighborhood", "opportunities", "opportunity",
    "collaborative", "transportation", "agricultural", "manufacturing",
    "engineering", "improvement", "preservation", "independent", "properties",
    "investments", "healthcare", "university", "children", "assistance",
    "coalition", "resources", "authority", "department", "consortium",
    "integrated", "landscaping", "remodeling", "maintenance",
)
# Real words (English, or a name's own spelling) that are such prefixes.
_WHOLE_WORDS = frozenset({
    "partners", "partner", "industrie", "technologie", "contract", "contractor",
    "develop", "construct", "conserve", "associate", "resource", "industrial",
    "enterprise", "restore", "renovation", "national", "solution", "engineer",
    "property", "investment", "independ", "transport", "community", "children",
    "neighbor", "environment", "residential", "commercial", "educational",
    "technical", "corporate", "integrate", "landscape", "remodel", "maintain",
    "cooperate", "administer", "institut", "behavior", "recreate",
})


def cut_off_word(name: str) -> str | None:
    """The fragment of a word the source cut off ("Conservati"), or None."""
    for word in re.findall(r"[A-Za-z]+", name or ""):
        low = word.lower()
        if len(low) < 8 or low in _WHOLE_WORDS or low in _LONG_WORDS:
            continue
        if any(w.startswith(low) for w in _LONG_WORDS):
            return word
    return None


# Words a source glues onto the one before ("RAFCONTRACTING INC"). A token that
# ENDS in one, after a few more letters, is FLAGGED and never split: "Raf
# Contracting" is likely, but the registered name may really be one word.
_GLUED_WORDS = (
    "contracting", "contractors", "construction", "builders", "services",
    "solutions", "roofing", "plumbing", "electric", "electrical", "consulting",
    "enterprises", "industries", "holdings", "properties", "management",
    "development", "foundation", "ministries", "landscaping", "remodeling",
    "engineering", "technologies", "group",
)
# Real prefixes: "Subcontracting", "Reconstruction", "Nonprofit...".
_GLUE_PREFIXES = frozenset({"sub", "re", "pre", "non", "co", "inter", "de", "self",
                            "home", "eco", "geo", "multi", "micro", "bio", "nano",
                            "info", "agri", "enviro", "petro", "aero", "hydro", "di"})


# Real single words that end in one of `_GLUED_WORDS`.
_GLUED_WHOLE = frozenset({"shipbuilders", "waterproofing", "homebuilders",
                          "boatbuilders", "subcontractors"})


def glued_word(name: str) -> str | None:
    """A token that looks like two words with the space lost ("Rafcontracting"),
    or None."""
    for word in re.findall(r"[A-Za-z]+", name or ""):
        low = word.lower()
        if low in _GLUED_WHOLE:
            continue
        for tail in _GLUED_WORDS:
            head = low[: -len(tail)]
            if low.endswith(tail) and len(head) >= 2 and head not in _GLUE_PREFIXES:
                return word
    return None


def _clean_company_name(name: str) -> str:
    """Tidy raw leadgen company names that get listed verbatim in the email —
    drop a trailing state-registration marker ("... / DE /"), stray separators,
    doubled whitespace, ALL-CAPS shouting, title-cased acronyms ("Wscadv" ->
    "WSCADV") and one-reading registry abbreviations ("Comn" -> "Community").
    Never guesses at a truncated name: `cut_off_word` flags it instead."""
    name = _REG_ARTIFACT_RE.sub("", name)
    # "Ioos Association, Inc. A/K/A Ioos Association": the alias repeats the
    # name, and a slash-acronym in an email reads as a filing.
    name = _AKA_RE.split(name, maxsplit=1)[0].rstrip(" ,")
    name = name.replace(" / ", " ").strip(" /|-")
    name = _MULTISPACE_RE.sub(" ", name).strip()
    return _fix_title_tokens(_fix_shouting(name))


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


# The two leadgen signal types that ASSERT a part-time engagement, mapped to what
# the evidence still supports when that assertion cannot be backed. Both fall to
# `job_finance_lead`: the posting is real and the seat is real, it is only the
# "fractional" word we cannot stand behind.
_FRACTIONAL_TYPES: dict[str, str] = {
    "job_fractional_cfo": "job_finance_lead",
    "job_fractional_controller": "job_finance_lead",
}


def _fractional_evidence(row: dict[str, Any]) -> tuple[str | None, bool]:
    """`(qualifier_to_prefix, is_evidenced)` for a fractional-tagged posting.

    leadgen tags a posting fractional when ANY of a wide word list — fractional,
    interim, part-time, outsourced, virtual, contract, temp, consultant,
    consulting, advisory — appears in the title OR anywhere in the description.
    Most of that list shows up incidentally in ordinary job copy ("advisory
    board", "consulting engagements", "contract negotiation"), so the TAG alone
    cannot carry a claim. Measured on the live inventory: 31 of 171 cfo and 22 of
    40 accounting fractional postings match only a weak word, including plain
    "Chief Financial Officer" titles at a law firm and a medical center.

    So the claim is re-derived here from the three words that are effectively
    never incidental and read naturally as an adjective:

      * `is_evidenced` — one of those three appears in the title or the body. The
        subject may say "fractional" only when this is True; see
        `adapt_leadgen_lead`, which downgrades the signal type when it is False.
      * `qualifier` — the word to PREFIX onto the printed role, or None. None
        when the title already says it (nothing to add) or when nothing does.

    Both halves come from one pass because they answer the same question, and
    they disagreed when they were two: the qualifier lookup used to run for
    `job_fractional_cfo` only, so 9 of 40 accounting leads printed a plain
    "controller" under a subject promising a fractional one.

    Scoped to signals matching the row's OWN `signal_type` — the posting the
    lead speaks for. A company can hold several postings, and reading a
    fractional word off one of them to justify a claim about another is the same
    mistake in a different direction."""
    primary_type = row.get("signal_type")
    if primary_type not in _FRACTIONAL_TYPES:
        return None, False
    qualifier: str | None = None
    evidenced = False
    for sig in row.get("signals") or []:
        if sig.get("type") != primary_type:
            continue
        payload = sig.get("payload") or {}
        title = str(payload.get("title") or sig.get("evidence_text") or "")
        if any(rx.search(title) for _q, rx in _QUALIFIER_RES):
            return None, True                # already visible in the printed role
        description = str(payload.get("description") or "")
        for word, rx in _QUALIFIER_RES:
            if rx.search(description):
                return word, True
    return qualifier, evidenced


# Public identifiers a magnet may carry, strongest first. An EIN or a CRD is a
# government-issued key with a public filing behind it; so is a UEI (SAM.gov
# registration), a state contractor license (Florida DBPR, Washington L&I) and
# a state business-registry ID ("CO:20261234567"). A domain is whatever the
# company registered. Order matters: a nonprofit with both should dedupe on
# its EIN, because two records for one charity can easily disagree about the
# website while never disagreeing about the EIN. The inventory's `publish`
# writes every ID it holds into the signal payload under these names.
_ID_FIELDS: tuple[tuple[str, str], ...] = (
    ("ein", "ein"), ("crd", "crd"), ("uei", "uei"),
    ("fl_license", "fl_license"), ("wa_license", "wa_license"), ("state_id", "state_id"),
    # The legal-duty families (2026-10-27): the inventory's other strong kinds
    # (`Inventory store.ID_ORDER`, written into a duty row's payload by
    # publish), then the program IDs a source keeps in its payload that name
    # one organization (a HUD owner, a DRE or TTB licensee, a Florida condo's
    # managing entity, a Texas engineering firm). Last, the number of the
    # public record itself (a tax warrant, a recorded lien, a Medicaid audit, a
    # gaming case, a tax-credit project) for a lead with no entity ID: it is
    # what a recipient types into the agency's search to see the record, which
    # is what "findable" means, and it keys the allocation log.
    ("cik", "cik"), ("ncua_charter", "ncua_charter"), ("npi", "npi"),
    ("state_license", "state_license"), ("tx_taxpayer", "tx_taxpayer"),
    ("mn_tax_id", "mn_tax_id"), ("opeid", "opeid"), ("nces_id", "nces_id"),
    ("cds_code", "cds_code"), ("olms_file_number", "olms_file_number"),
    ("ny_municode", "ny_municode"), ("hud_owner_participant_id", "hud_owner"),
    ("dre_license_number", "dre_license"), ("dbpr_managing_entity_number", "fl_condo_entity"),
    ("ttb_permit", "ttb_permit"), ("tbpels_firm", "tbpels_firm"),
    ("warrant_ids", "ny_warrant"), ("lien_filing_number", "lien"),
    ("document_id", "acris_doc"), ("audit_number", "omig_audit"), ("ngc_case", "ngc_case"),
    ("ctcac_application_number", "tcac_project"), ("njeda_product_id", "njeda_project"),
)

_EIN_DIGITS_RE = re.compile(r"\D")


def _id_value(key: str, raw: Any) -> str:
    """One spelling per ID. An EIN arrives as "41-1386089" from the 990 and as
    "411386089" from the IRS BMF (the grant magnet); both are the same charity,
    so a 9-digit EIN is written in the IRS's dashed form."""
    if isinstance(raw, (list, tuple)):        # NY: one lead, several warrant numbers
        raw = raw[0] if raw else ""
    value = str(raw).strip()
    if key == "ein":
        digits = _EIN_DIGITS_RE.sub("", value)
        if len(digits) == 9:
            return f"{digits[:2]}-{digits[2:]}"
    return value


def _entity_id(row: dict[str, Any]) -> str | None:
    """`"ein:27-1693939"` / `"uei:RFCKU47QJQK3"` / `"domain:acme.com"` / None."""
    for key, prefix in _ID_FIELDS:
        for signal in (row.get("signals") or []):
            raw = (signal.get("payload") or {}).get(key)
            if raw not in (None, "", [], ()) and str(raw).strip():
                return f"{prefix}:{_id_value(key, raw)}"
    domain = (row.get("domain") or "").strip().lower()
    return f"domain:{domain}" if domain else None


def adapt_leadgen_lead(row: dict[str, Any], *, today: date) -> Lead:
    """Map one leadgen inventory row onto the outreach `Lead` shape.

    Field mapping:
      company     <- row["name"]
      value_prop  <- row.get("insight")
      signal_type <- row["signal_type"], EXCEPT a fractional tag we cannot
                     evidence, which reads as `job_finance_lead`
                     (see `_fractional_evidence`)
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
    industry, niche = _taxonomy_tags(row.get("industry"), row.get("niche"))

    primary = _primary_signal(row)
    freshness = _freshness(primary.get("event_date"), today)
    # Contract v2: the source says how long the lead holds (`expires_at`; one
    # past it never gets here, see `_past_expiry`), so an active v2 lead IS
    # current. Its event date is when a DOCUMENT was filed: judged by it, every
    # 990-dated charity read "stale" and the gift walk's fresh round handed
    # every place to recent grants and licenses, so the strength order
    # (charity audit problems first) never applied.
    if row.get("expires_at") and row.get("status", "active") == "active":
        freshness = "fresh"

    # A fractional tag we cannot evidence is downgraded HERE, once, rather than
    # special-cased at each place that reads the type. Doing it at the door means
    # the subject WHAT, the pack's signal rank, the lead-first priority pick and
    # the DM all agree without any of them knowing this rule exists — and a
    # posting can never be ranked as explicit in-market intent on a word its own
    # body used for something else.
    qualifier, evidenced = _fractional_evidence(row)
    signal_type = row["signal_type"]
    downgrade = (
        _FRACTIONAL_TYPES.get(signal_type) if not evidenced else None
    )
    if downgrade is not None:
        log.debug("inventory: %s — %s not evidenced, reading it as %s",
                  company, signal_type, downgrade)
        signal_type = downgrade

    signals = [
        Signal(
            # Re-typed in lockstep with `signal_type` above, so nothing reading a
            # signal can revive a claim the lead itself has already dropped.
            type=(_FRACTIONAL_TYPES.get(str(s.get("type")))
                  if downgrade is not None and s.get("type") in _FRACTIONAL_TYPES
                  else s.get("type")),
            date=s.get("event_date"),
            # Read it, never assume it. Hardcoding "high" meant a first-seen
            # stamp was rendered as a recency claim: the fractional board
            # publishes no posting date, so its leads printed "about 2 weeks
            # ago" off a Webflow site-build timestamp. `copy.honesty.date_suffix`
            # already suppresses a date on anything not "high" -- it just never
            # got the chance. Older inventory carries no field, and defaulting
            # those to "high" is right: every other source publishes a real
            # posting, filing or disclosure date.
            date_confidence=s.get("date_confidence") or "high",
            plain_words_description=s.get("evidence_text"),
            source_url=s.get("source_url"),
            payload=s.get("payload") or {},
        )
        for s in (row.get("signals") or [])
    ]

    lead_id = row.get("id") or _synthesize_id(niche, company, row.get("state"))

    return Lead(
        id=str(lead_id),
        entity_id=_entity_id(row),
        company=company,
        name_glued=glued_word(company),
        name_cut_off=cut_off_word(company),
        domain=row.get("domain"),
        city=row.get("city"),
        state=row.get("state"),
        industry=industry,
        niche=niche,
        value_prop=row.get("insight"),
        headcount=row.get("headcount"),
        headcount_band=row.get("headcount_band"),
        # The magnet's own ranking of how strong this lead is. The live job-post
        # API never served one, so the field sat permanently None and
        # `sort_key` had nothing to order by within a signal type. The vertical
        # magnets DO score — it is how a repeat material-weakness finding
        # outranks an ordinary grant-funded nonprofit — so it is read here.
        score=row.get("score"),
        role_qualifier=qualifier,
        service_tags=[str(t) for t in (row.get("service_tags") or [])],
        signal_type=signal_type,
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
    # Canonical copy, vendored here. The taxonomy used to ship from the leadgen
    # blob, but it is a CONTRACT rather than data: the lead magnets emit into
    # this vocabulary and the research classifier maps prospects into it, so it
    # belongs with the consumer that defines it. Vendoring it also means
    # retiring the leadgen job-post pipeline cannot take the taxonomy with it.
    if LOCAL_TAXONOMY.exists():
        return dict((json.loads(LOCAL_TAXONOMY.read_text()) or {}).get("taxonomy") or {})
    return {}


def lead_age_days(lead: Lead, today: date) -> int | None:
    """Age of the posting this lead SPEAKS FOR, or None when it cannot be dated.

    Read off `headline_signal`, not the newest date on the record: a company
    with several postings would otherwise borrow a fresh posting's date to keep
    an old headline alive, which is the same subject/body mismatch
    `headline_signal` exists to close."""
    headline = lead.headline_signal
    raw = headline.date if headline is not None else None
    if not raw:
        raw = max((s.date for s in lead.signals if s.date), default=None)
    if not raw:
        return None
    try:
        return (today - date.fromisoformat(str(raw)[:10])).days
    except ValueError:
        return None


def _max_age_for(lead: Lead) -> int:
    """The age ceiling that applies to this lead. The fractional tier gets the
    wider window (see `config.MAX_FRACTIONAL_LEAD_AGE_DAYS`)."""
    if lead.signal_type in _FRACTIONAL_TYPES:
        return config.MAX_FRACTIONAL_LEAD_AGE_DAYS
    return config.MAX_JOB_LEAD_AGE_DAYS


# Age ceilings by SIGNAL FAMILY. A job post decays fast because "is looking for
# a bookkeeper" stops being true the moment the role is filled. A structural
# signal does not decay the same way — an unadministered fund or a disclosed
# material weakness describes how the business is ARRANGED, not something it is
# doing this month — but it can still go stale as a fact about a filing, so
# each family declares its own rule instead of inheriting the job-post one.
#
#   None  = no ceiling. The claim is about a document that stays true, and the
#           magnet already re-tests currency at its own source (the nonprofit
#           magnet, for instance, refuses to headline an audit finding more
#           than two years behind the return it quotes).
_STRUCTURAL_MAX_AGE_DAYS: dict[str, int | None] = {
    # Form ADV is filed annually, so a filing older than about 18 months means
    # the adviser has missed a cycle and the fund counts cannot be trusted.
    "adv_": 550,
    # The 990 lag is structural (charities file late, the IRS posts later) and
    # is stated inside the evidence line itself, so a date cap here would only
    # delete honest leads.
    "nonprofit_": None,
    # A storefront crawl is a live observation with no event date at all.
    "ecommerce_": None,
    # The inventory's own families (contract v2). No extra ceiling here: each
    # lead carries its own `expires_at`, set by its source from the window it
    # was found in (a 180-day award window, a 90-day license or formation
    # window), and `_past_expiry` drops it on that date.
    "construction_": None,
    "federal_": None,
    "new_business_": None,
}


def _structural_max_age(signal_type: str) -> tuple[bool, int | None]:
    """(is_structural, max_age_days). max_age None means no ceiling."""
    for prefix, cap in _STRUCTURAL_MAX_AGE_DAYS.items():
        if (signal_type or "").startswith(prefix):
            return True, cap
    return False, None


def _is_expired_job_lead(lead: Lead, today: date) -> bool:
    """True when a lead is too old to be shown.

    Job postings decay fast: "is looking for a {role}" stops being true once
    the role is filled, and an undated one cannot be shown to be open at all.

    Structural signals are governed by `_STRUCTURAL_MAX_AGE_DAYS` instead. They
    are NOT simply exempt — that was true only by accident, because their
    signal types happen not to start with "job_", and a future magnet whose
    filings genuinely go stale would have inherited no rule at all.
    """
    signal_type = lead.signal_type or ""
    structural, cap = _structural_max_age(signal_type)
    if structural:
        if cap is None:
            return False
        age = lead_age_days(lead, today)
        # An undated structural lead is KEPT — unlike a job post, absence of a
        # date is normal here (a crawl has none) and says nothing about whether
        # the arrangement still holds.
        return age is not None and age > cap
    if not signal_type.startswith("job_"):
        return False
    age = lead_age_days(lead, today)
    if age is None:
        return True          # undated job posting: cannot show it is still open
    return age > _max_age_for(lead)


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


# Form 5500 plan sponsors: individuals file under their plain names.
_SPONSOR_TYPES = frozenset({
    "plan_audit_first_due", "plan_audit_first_filed", "plan_late_contributions",
    "plan_termination_pending", "plan_prohibited_transaction",
    "pension_unpaid_min_contribution", "welfare_plan_audit_threshold", "plan_fraud_loss",
    "plan_audit_opinion_modified"})


def _duty_types() -> frozenset[str]:
    from system_b.copy.duty import DUTY_SIGNALS   # lazy: copy imports gift, not clients
    return DUTY_SIGNALS


def _unusable_reason(row: dict[str, Any], lead: Lead) -> str | None:
    """Why this lead can never make an honest gift line, or None when it can."""
    if _has_id_suffix(lead.company):
        return "id_suffixed_name"
    # The raw registry name: "S SATO LLC" prints as "S Sato".
    if lead.signal_type in _duty_types() and looks_like_person(
            row.get("name") or lead.company, strict=lead.signal_type in _SPONSOR_TYPES):
        return "person_name"
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


def _past_expiry(row: dict[str, Any], today: date) -> bool:
    """Contract v2: a magnet stamps each lead with `expires_at` and `status`.
    Re-checked here because an inventory can sit unread past the date it was
    emitted. A row without the fields (contract v1) is judged by the older
    per-family rules below, unchanged."""
    if row.get("status") == "stale":
        return True
    exp = row.get("expires_at")
    if not exp:
        return False
    try:
        return date.fromisoformat(str(exp)[:10]) < today
    except ValueError:
        return False


def _adapt_rows(rows: list[dict[str, Any]], *, today: date) -> list[Lead]:
    kept: list[Lead] = []
    expired = 0
    unusable: Counter[str] = Counter()
    lapsed = 0
    for row in rows:
        if _past_expiry(row, today):
            lapsed += 1
            continue
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
    if lapsed:
        log.info("inventory: dropped %d lead(s) past their own expires_at", lapsed)
    if unusable:
        log.info("inventory: dropped %d unusable lead(s): %s",
                 sum(unusable.values()), dict(unusable.most_common()))
    return kept


# --- Lead magnets -----------------------------------------------------------
#
# The inventory used to be one file per NICHE — which rung of service a firm
# sells (bookkeeping / accounting / cfo). Those files came from the job-post
# pipeline, and job posts were retired as gift content: a company advertising
# for a bookkeeper has decided to hire in-house, and a "Fractional CFO wanted"
# post is on every job board, so handing one to a prospect proves nothing.
#
# What replaced them is one file per VERTICAL — which industry a firm serves.
# The two are orthogonal: a prospect is a rung AND a vertical ("a fractional
# CFO who serves nonprofits"). The rung still selects the copy voice (--pack);
# the vertical selects which leads they can be shown at all.
#
# Every magnet now comes out of the lead inventory (~/Developer/Inventory):
# `python -m leadinv.run publish` writes one file per lead type into
# Inventory/exports/magnets/, which is what LEADGEN_INVENTORY_DIR points at.
# Each file is its source's own contract-v2 records with the inventory's
# websites, contacts, IDs and 0-100 strength laid over them.
#
# Funds and ecommerce are switched off upstream (the MVP uses free sources
# only), so they are not listed; their adapters and copy stay.
MAGNETS: dict[str, str] = {
    "nonprofit": "nonprofit-leads.json",          # Row 1: IRS Form 990 + Federal Audit Clearinghouse
    "construction": "construction-leads.json",    # Row 7: Davis-Bacon awards, FL + WA licenses
    "govcon": "govcon-leads.json",                # Row 5: cost-type federal contracts
    "grant": "grant-leads.json",                  # Row 6: first federal grant in 3+ years
    "newbusiness": "new-business-leads.json",     # Row 8: CO + CT new LLCs / corporations
    # The legal-duty families (2026-10-27): only their approved types
    # (Inventory sources.APPROVED_SIGNALS); wording in copy/duty.py.
    "nonprofitduty": "nonprofit-duty-leads.json",       # 990 lines, FAC late / questioned
    "benefits": "benefits-leads.json",                  # Form 5500 plan duties
    "taxtrouble": "tax-trouble-leads.json",             # tax liens, warrants, CA top 500
    "healthcare": "healthcare-leads.json",              # Medicare enrollments, CHOWs, OMIG, HRSA
    "property": "property-leads.json",                  # HUD owners, TCAC, DRE/NC discipline
    "securities": "securities-leads.json",              # SEC 8-K / NT / X-17A-5, NCUA
    "publicsector": "public-sector-leads.json",         # HCM, 90/10, schools, local gov, unions
    "specialty": "specialty-leads.json",                # TTB, A/E rates, CPUC, NV gaming, film
    "constructionduty": "construction-duty-leads.json",  # WA prevailing wage, NV, FL stop-work
    "govconduty": "govcon-duty-leads.json",             # first SBIR Phase II
}
# The original five: a run that finds one of THESE empty stops (morning);
# a duty family may legitimately publish nothing for a week.
CORE_MAGNETS: frozenset[str] = frozenset(
    {"nonprofit", "construction", "govcon", "grant", "newbusiness"})

# magnet key -> the taxonomy PARENT its leads carry, or None when the
# industry differs lead by lead. Kept here as the one place that has to agree
# with each source's own tagging, so a rename shows up as a mismatch in one
# file rather than as leads that silently never match.
MAGNET_INDUSTRY: dict[str, str | None] = {
    "nonprofit": "nonprofit",
    "construction": "construction",
    "govcon": "government_contracting",
    # A grant recipient is a nonprofit (tagged `nonprofit`) or a business with
    # no industry on the award (untagged -> generalist, city/state only).
    "grant": None,
    # From the NAICS code each registry filing states, when it states one.
    "newbusiness": None,
    "nonprofitduty": "nonprofit",
    "benefits": None,             # the employer's NAICS on its Form 5500
    "taxtrouble": None,           # no industry on a lien
    "healthcare": "healthcare",
    "property": "real_estate",
    "securities": None,           # SIC divisions: not taxonomy words (_taxonomy_tags)
    "publicsector": None,         # schools -> education; governments, unions none
    "specialty": None,            # per program (_taxonomy_tags)
    "constructionduty": "construction",
    "govconduty": "government_contracting",
}

# A duty source's own (industry, niche) words, by niche, mapped onto the
# vendored taxonomy (data/taxonomy.json is the contract; a lead tagged outside
# it can never match a prospect, and Gate B would judge it for nothing).
# None = no vertical: the lead is a city/state (generalist) gift only.
_SOURCE_NICHES: dict[str, tuple[str | None, str | None]] = {
    # Healthcare
    "hospital": ("healthcare", None), "healthcare": ("healthcare", None),
    "health_center": ("healthcare", "medical_practice"),
    "rural_health_clinic": ("healthcare", "medical_practice"),
    "clinic": ("healthcare", "medical_practice"),
    "home_health": ("healthcare", "senior_care"), "hospice": ("healthcare", "senior_care"),
    "skilled_nursing": ("healthcare", "senior_care"),
    # Property
    "real_estate_brokerage": ("real_estate", "brokerage"),
    "condo_association": ("real_estate", "property_management"),
    "hoa": ("real_estate", "property_management"),
    "hud_multifamily": ("real_estate", "real_estate_investment"),
    "lihtc": ("real_estate", "real_estate_investment"),
    # Public sector
    "higher_education": ("education", "higher_ed"),
    "charter_school": ("education", "k12_school"),
    "k12_private_choice": ("education", "k12_school"),
    "school_district": ("education", "k12_school"),
    "local_government": (None, None), "special_district": (None, None),
    "labor_union": (None, None),
    # Securities (SIC divisions are not verticals, and these leads carry no
    # insight for Gate B to judge): geography only.
    "public_company": (None, None), "broker_dealer": (None, None),
    "credit_union": (None, None), "reg_a_issuer": (None, None),
    "crowdfunding_issuer": (None, None),
    # Specialty
    "engineering": ("professional_services", "architecture_engineering"),
    "film_tv_production": ("media_entertainment", "production_studio"),
    "casino_gaming": ("hospitality_food", None),
    "winery": ("ecommerce_retail", "cpg_food_beverage"),
    "distillery": ("ecommerce_retail", "cpg_food_beverage"),
    "water_utility": ("energy", "utilities"), "sewer_utility": ("energy", "utilities"),
    # Federal duty
    "8a": ("government_contracting", None), "sbir_sttr": ("government_contracting", None),
}


def _taxonomy_tags(industry: str | None, niche: str | None) -> tuple[str | None, str | None]:
    """(industry, niche) in the taxonomy's own words. A duty source's niche word
    maps through `_SOURCE_NICHES`; anything else passes through unchanged (the
    original five already emit taxonomy words)."""
    if niche in _SOURCE_NICHES:
        return _SOURCE_NICHES[niche]
    return industry, niche


def _load_one(name: str, key: str, today: date) -> list[dict[str, Any]]:
    """Raw rows for one magnet, blob first then local dir. A magnet that is not
    published yet is skipped with a warning rather than failing the run — a
    missing one is normal, not broken."""
    inventory_dir = os.environ.get("LEADGEN_INVENTORY_DIR")
    data: dict[str, Any] | None = None

    if _blob_base():
        try:
            data = _fetch_blob_json(name)
        except Exception:  # noqa: BLE001 — a missing magnet must not end the run
            # Not fatal, and not the end of the search. The three magnets
            # publish on their own cadence, so one of them being absent from
            # the blob is ordinary — and a local copy is the better answer than
            # skipping when the operator has one. Blob stays FIRST so a normal
            # run reads what is actually published.
            log.warning("inventory: %s not on the blob — trying local", name)

    if data is None:
        if not inventory_dir:
            if _blob_base():
                log.warning("inventory: %s unavailable and no local dir set — skipping", name)
                return []
            raise RuntimeError(
                "no inventory source: set LEADGEN_BLOB_BASE_URL or LEADGEN_INVENTORY_DIR"
            )
        path = Path(inventory_dir) / name
        if not path.exists():
            log.warning("inventory: %s not found in %s — skipping", name, inventory_dir)
            return []
        data = json.loads(path.read_text())

    _check_freshness(data, key, today)
    return list(data.get("leads") or [])


def snapshot_all_magnets(today: date | None = None) -> SnapshotScraper:
    """Every vertical magnet in ONE addressable snapshot.

    The leads stay logically separate — each carries its own `industry`, and
    the gift ladder only ever queries one vertical at a time — but they live in
    one scraper because that is the interface `build_gift` already speaks. No
    change to the gift engine is needed.

    A magnet that fails to load is skipped, not fatal: the three refresh
    independently and a run with two of them is still a useful run.
    """
    today = today or date.today()
    rows: list[dict[str, Any]] = []
    per_magnet: dict[str, int] = {}
    for key, name in MAGNETS.items():
        loaded = _load_one(name, key, today)
        per_magnet[key] = len(loaded)
        rows.extend(loaded)
    if not rows:
        raise RuntimeError(
            f"no lead magnet produced any rows (looked for {list(MAGNETS.values())}). "
            "Run `cd ~/Developer/Inventory && .venv/bin/python -m leadinv.run publish` and "
            "point LEADGEN_INVENTORY_DIR at Inventory/exports/magnets."
        )
    leads = _adapt_rows(rows, today=today)
    log.info("inventory(magnets): %d lead(s) — %s", len(leads), per_magnet)
    return SnapshotScraper(leads, taxonomy=load_taxonomy())


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
    if niche_key in RETIRED_JOB_NICHES and not os.environ.get("LEADGEN_ALLOW_RETIRED"):
        raise RuntimeError(
            f"the {niche_key!r} job-post inventory was retired on 2026-09-08 and is "
            "no longer refreshed — anything still on the blob is stale. Use the "
            "vertical magnets (drop --legacy-niche), or set LEADGEN_ALLOW_RETIRED=1 "
            "to read the old file deliberately."
        )
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
