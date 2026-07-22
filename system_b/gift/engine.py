"""Step 3 — build the gift (pure logic).

3a fractional-CFO check, 3b two-round Level 1-5 walk, 3c count, 3d best
lead, 3e honesty values. Geography-first: gift is assembled by match
level; signal type then date are tiebreaks WITHIN a level (except 3a).

Sort note (field-name reality): the live API exposes no `score`, so the
within-level re-sort is `signal-type rank -> newest date -> date_confidence
(high before low)`. Best-lead selection is `signal-type rank -> freshness
-> match level` (score dropped).

If System A later adds `score`, it slots into the MIDDLE of each key,
directly AFTER signal-type rank (spec 3b: "rank, then score, then newest
date"; spec 3d: "signal type, then score, then freshness"). It is never
appended at the end:
  * sort_key:  rank -> [-score] -> newest-date -> confidence
  * _best_lead: rank -> [-score] -> freshness -> match-level
See the `# <-- score slots here` markers in both functions.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol

from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import NichePack, default_pack

# Strongest -> weakest, in leadgen's raw signal-type vocabulary. This is the CFO
# pack's rank (imported by niches/cfo.py); every pack now supplies its own
# `signal_rank`, which the tiebreak sorts read via the `rank` arg. A lead whose
# signal isn't in the active rank map ranks last (9).
SIGNAL_RANK: dict[str, int] = {
    "job_fractional_cfo": 0,
    "job_finance_lead": 1,
    "funding_form_d": 2,
}
# Funding signal types (SEC Form D/C) — a lead whose primary signal is one of
# these is a "raise" for copy/what-category purposes.
FUNDING_SIGNALS: frozenset[str] = frozenset({"funding_form_d", "funding_form_c"})
GIFT_TARGET = 3

_US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "rhode island": "ri",
    "south carolina": "sc", "south dakota": "sd", "tennessee": "tn", "texas": "tx",
    "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
    "district of columbia": "dc", "puerto rico": "pr",
}


class _Scraper(Protocol):
    def leads(self, **params: Any) -> list[Lead]: ...


def norm_loc(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def norm_state(s: str | None) -> str:
    n = norm_loc(s)
    return _US_STATES.get(n, n)


def _recency(lead: Lead) -> float:
    d = lead.newest_date
    if not d:
        return float("-inf")
    try:
        return datetime.fromisoformat(d[:19]).timestamp()
    except ValueError:
        return float("-inf")


def sort_key(lead: Lead, rank: dict[str, int] | None = None) -> tuple[int, float, int]:
    """Within-level re-sort: strongest signal (per the active pack's
    `signal_rank`), then freshest, then high-confidence date before low."""
    rank = rank if rank is not None else SIGNAL_RANK
    return (
        rank.get(lead.signal_type, 9),
        # <-- score slots here: -(lead.score or 0), once System A serves it
        -_recency(lead),
        0 if lead.effective_date_confidence == "high" else 1,
    )


def compute_match_level(lead: Lead, prospect: Prospect) -> int | None:
    """How closely `lead` matches `prospect`. Niched: 1 niche+city, 2
    niche+state, 3 niche, 4 city, 5 state. Generalist: 1 city, 2 state.
    None = no match (should not be in a gift)."""
    niche_match = False
    if prospect.match_param:
        kind, val = prospect.match_param
        if kind == "niche":
            niche_match = lead.niche == val
        elif kind == "industry":
            niche_match = lead.industry == val
    city_match = bool(
        lead.city and prospect.city and norm_loc(lead.city) == norm_loc(prospect.city)
    )
    state_match = bool(
        lead.state and prospect.state and norm_state(lead.state) == norm_state(prospect.state)
    )
    if prospect.classification == "niched":
        if niche_match and city_match:
            return 1
        if niche_match and state_match:
            return 2
        if niche_match:
            return 3
        if city_match:
            return 4
        if state_match:
            return 5
        return None
    if city_match:
        return 1
    if state_match:
        return 2
    return None


def _levels_for(p: Prospect, *, niche_only: bool = False) -> list[tuple[int, dict[str, Any]]]:
    levels: list[tuple[int, dict[str, Any]]] = []
    if p.classification == "niched" and p.match_param:
        kind, val = p.match_param
        base = {kind: val}
        if p.city:
            levels.append((1, {**base, "city": p.city}))
        if p.state:
            levels.append((2, {**base, "state": p.state}))
        levels.append((3, dict(base)))
        # niche_only (Change 2 / Gate B): stop at L3 so the gift is entirely
        # on-niche leads. Dropping the L4/L5 geo fallback means the gift is
        # either all_niche or empty — never padded with off-niche leads.
        if niche_only:
            return levels
        if p.city:
            levels.append((4, {"city": p.city}))
        if p.state:
            levels.append((5, {"state": p.state}))
    else:
        if p.city:
            levels.append((1, {"city": p.city}))
        if p.state:
            levels.append((2, {"state": p.state}))
    return levels


def _find_priority_lead(
    prospect: Prospect, scraper: _Scraper, excluded: set[str], *,
    pack: NichePack, niche_only: bool = False,
) -> Lead | None:
    """3a: the pack's priority signal (CFO: cfo_wanted) via match_param, then
    city, then state (fresh). First query with a hit wins; its best (re-sorted)
    lead is returned. Packs with no priority signal (e.g. trucking) short-circuit."""
    if not pack.priority_signal:
        return None
    queries: list[dict[str, Any]] = []
    if prospect.classification == "niched" and prospect.match_param:
        kind, val = prospect.match_param
        queries.append({kind: val})
    # niche_only: don't fall back to a geo priority lead — it would be off-niche.
    if not niche_only:
        if prospect.city:
            queries.append({"city": prospect.city})
        if prospect.state:
            queries.append({"state": prospect.state})
    for kwargs in queries:
        leads = [
            l for l in scraper.leads(
                signal_type=pack.priority_signal, freshness="fresh",
                exclude_ids=list(excluded), **kwargs,
            )
            if l.id not in excluded
        ]
        if leads:
            leads.sort(key=lambda l: sort_key(l, pack.signal_rank))
            return leads[0]
    return None


def _pick_leads(
    prospect: Prospect, scraper: _Scraper, excluded: set[str], *, target: int,
    into: list[Lead], rank: dict[str, int], niche_only: bool = False,
) -> None:
    """The two-round Level walk. Mutates `into` / `excluded` in place."""
    levels = _levels_for(prospect, niche_only=niche_only)
    for freshness in ("fresh", "stale"):
        if len(into) >= target:
            return
        for _level, kwargs in levels:
            if len(into) >= target:
                return
            leads = [
                l for l in scraper.leads(
                    freshness=freshness, exclude_ids=list(excluded), **kwargs,
                )
                if l.id not in excluded
            ]
            leads.sort(key=lambda l: sort_key(l, rank))
            for lead in leads:
                if len(into) >= target:
                    break
                into.append(lead)
                excluded.add(lead.id)


def build_gift(
    prospect: Prospect, scraper: _Scraper, *, target: int = GIFT_TARGET,
    niche_only: bool = False, pack: NichePack | None = None,
) -> Gift | None:
    """Build the gift. `niche_only` (Change 2 / Gate B) restricts to on-niche
    leads (levels 1-3): the returned gift is all_niche or None, never padded
    with geo leads — so the tiering resolver can test a candidate niche.

    `pack` supplies the niche's priority signal and WHAT categorization;
    defaults to the CFO pack so existing callers are unchanged."""
    pack = pack or default_pack()
    rank = dict(pack.signal_rank)
    gift: list[Lead] = []
    excluded: set[str] = set(prospect.sent_lead_ids)

    lead = _find_priority_lead(prospect, scraper, excluded, pack=pack, niche_only=niche_only)
    if lead is not None:
        gift.append(lead)
        excluded.add(lead.id)

    _pick_leads(prospect, scraper, excluded, target=target, into=gift, rank=rank, niche_only=niche_only)

    if not gift:
        return None

    best = _best_lead(gift, prospect, rank)
    all_niche, geo = _honesty(gift, prospect)
    has_priority = bool(pack.priority_signal) and any(
        l.signal_type == pack.priority_signal for l in gift
    )
    shape = "singular" if (len(gift) == 1 or has_priority) else "plural"
    return Gift(
        leads=gift,
        best_lead=best,
        gift_size=len(gift),
        all_niche=all_niche,
        geo_level=geo,
        subject_shape=shape,
        what_category=pack.what_category(gift),
        best_lead_level=compute_match_level(best, prospect),
    )


def pull_one_lead(
    prospect: Prospect, scraper: _Scraper, *, pack: NichePack | None = None
) -> Lead | None:
    """Follow-up pull (Steps 6/7): ONE new lead, same levels, exclude_ids
    already sent. The priority signal (3a) still leads. Copy layer decides
    value/fallback; this returns the lead."""
    gift = build_gift(prospect, scraper, target=1, pack=pack)
    return gift.leads[0] if gift else None


def _best_lead(gift: list[Lead], prospect: Prospect, rank: dict[str, int] | None = None) -> Lead:
    rank = rank if rank is not None else SIGNAL_RANK
    def key(lead: Lead) -> tuple[int, int, int]:
        return (
            rank.get(lead.signal_type, 9),
            # <-- score slots here: -(lead.score or 0), once System A serves it
            0 if lead.freshness == "fresh" else 1,
            compute_match_level(lead, prospect) or 99,
        )
    return min(gift, key=key)


def _honesty(gift: list[Lead], prospect: Prospect) -> tuple[bool, str]:
    if prospect.classification == "niched":
        all_niche = all((compute_match_level(l, prospect) or 99) <= 3 for l in gift)
    else:
        all_niche = False

    def city_ok(l: Lead) -> bool:
        return bool(l.city and prospect.city and norm_loc(l.city) == norm_loc(prospect.city))

    def state_ok(l: Lead) -> bool:
        return bool(l.state and prospect.state and norm_state(l.state) == norm_state(prospect.state))

    if all(city_ok(l) for l in gift):
        geo = "city"
    elif all(state_ok(l) for l in gift):
        geo = "state"
    else:
        geo = "none"
    return all_niche, geo


def _cfo_what_category(gift: list[Lead]) -> str:
    """CFO subject WHAT category. Lives here (not the pack module) because it's
    pure signal logic; the CFO pack references it by name. In leadgen's vocab a
    lead's primary signal is either a funding filing (a raise) or a job post (a
    hire)."""
    def raised(l: Lead) -> bool:
        return l.signal_type in FUNDING_SIGNALS

    def hiring(l: Lead) -> bool:
        return l.signal_type not in FUNDING_SIGNALS

    if all(raised(l) for l in gift):
        return "raised"
    if all(hiring(l) for l in gift):
        return "hiring"
    return "mixed"
