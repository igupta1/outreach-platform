"""Change 2 — three-tier niche resolution (Gate B + framing verb selection).

Research (Step 2a) already applied GATE A: every candidate in
`research.candidate_match_params` is an industry the prospect stated VERBATIM
on their own site. This layer applies GATE B: a niche is only claimed if the
LIVE leads can fill an all-niche gift for it (`build_gift(..., niche_only=True)`
returns a gift and `gift.all_niche` is True). Among the candidates that pass,
we claim the best-supplied one.

The tier (and therefore the framing verb) falls out of the outcome:
  * sole            — a single stated focus (or a client list); soft verb "work with"
  * one_of_several  — one of several stated industries;          soft verb "work with"
  * none            — nothing fills a good niche gift → generalist geo copy

An honest generalist email beats a niche claim the leads don't back, so if no
candidate passes Gate B we drop to the generalist gift.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from system_b.copy.lex import niche_display
from system_b.gift.engine import GIFT_TARGET, build_gift, single_kind_gift
from system_b.gift.fit import claim_check, fit_check
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import NichePack, default_pack
from system_b.research.models import ResearchResult
from system_b.research.rung import detect_cpa

# Gate B fit-check: (niche_label, leads) -> per-lead booleans. Injectable so
# tests run offline; production passes the real LLM check.
FitFn = Callable[[str, list[Lead]], list[bool]]
# (verbatim phrase, niche label, every phrase the site lists) -> does the
# phrase say the firm serves that industry?
ClaimFn = Callable[[str, str, tuple[str, ...]], bool]


class _Scraper:  # structural: anything with .leads(**params)
    def leads(self, **params: Any) -> list: ...  # pragma: no cover


def _base_prospect(row: dict[str, Any], research: ResearchResult, **kw: Any) -> Prospect:
    return Prospect(
        firm_name=row["firm_name"],
        city=row.get("city"),
        state=row.get("state"),
        niche_phrase=research.niche_phrase,
        niche_source=research.niche_source or "site",
        first_name=row.get("first_name"),
        client_names=list(getattr(research, "nameable_clients", None) or []),
        client_revenue=getattr(research, "client_revenue", None),
        sent_lead_ids=list(row.get("sent_lead_ids") or []),
        blocked_identities=frozenset(row.get("blocked_identities") or ()),
        focus=getattr(research, "rung_focus", None),
        rung=getattr(research, "rung", None),
        is_cpa=bool(getattr(research, "cpa", False))
               or detect_cpa(None, firm_name=row.get("firm_name"), title=row.get("title")),
        **kw,
    )


def fit_label(mp: tuple[str, str], label: str, phrase: str | None) -> str:
    """What the fit check judges leads against. A broad INDUSTRY candidate is
    judged against the firm's own words too: hospices are "healthcare", but
    not what a firm serving "Biotech Startups" serves (2026-11-05)."""
    if mp[0] == "niche" or not phrase or phrase.strip().lower() == label.strip().lower():
        return label
    return (f"{label}, specifically the kind of client this firm names in its own words: "
            f"\"{phrase.strip()}\" (a company of another kind within {label} does not fit)")


_TAXONOMY_JSON = Path(__file__).resolve().parents[1] / "data" / "taxonomy.json"


@lru_cache(maxsize=1)
def _parents() -> dict[str, str]:
    """{niche: its industry} from data/taxonomy.json; {} when unreadable."""
    try:
        data = json.loads(_TAXONOMY_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tax = data.get("taxonomy", data) if isinstance(data, dict) else {}
    return {child: parent for parent, children in tax.items() for child in (children or [])}


def _broad(mp: tuple[str, str]) -> tuple[str, str] | None:
    """The plain-industry fallback for a candidate: the niche's parent
    industry, or the same industry judged without the firm's exact words."""
    if mp[0] == "niche":
        parent = _parents().get(mp[1])
        return ("industry", parent) if parent else None
    return mp


def _supply_key(gift: Gift, rank: dict[str, int]) -> tuple[int, int]:
    """Rank candidate gifts by lead supply: more leads first, then a stronger
    best-lead signal (per the active pack's rank). All contenders are all-niche."""
    return (gift.gift_size, -rank.get(gift.best_lead.signal_type, 9))


def _candidate_pairs(research: ResearchResult) -> list[tuple[tuple[str, str], str]]:
    """(match_param, verbatim_phrase) for each candidate, aligned. Falls back to
    the primary niche_phrase if per-candidate phrases weren't recorded."""
    if research.classification != "niched":
        return []
    phrases = research.candidate_phrases or []
    out: list[tuple[tuple[str, str], str]] = []
    for i, mp in enumerate(research.candidate_match_params):
        phrase = phrases[i] if i < len(phrases) else (research.niche_phrase or "")
        out.append((mp, phrase))
    return out


# How many stated verticals to test against live leads before giving up. The
# average firm states three; six would be a firm listing everything it has ever
# touched, and the fourth candidate has never been the one that lands.
log = logging.getLogger("system_b.gift")

# Counted only for candidates that reach the fit check (a vertical with no
# local leads costs nothing). Was 3 until 2026-11-04: Delightful Digits lists
# seven industries, its first three failed, and real estate and nonprofits,
# both of which pass, were never tried.
MAX_FIT_CANDIDATES = 6
# The spend bound: fit calls (each swap is one) across all candidates.
MAX_FIT_CALLS = 12


def _fitting_niche_gift(
    trial: Prospect, scraper: _Scraper, pack: NichePack,
    label: str, fit: FitFn, *, max_swaps: int = 3,
) -> Gift | None:
    """Build an all-niche gift whose leads ALL pass the fit check. A lead that
    fails fit is excluded and a replacement pulled (up to `max_swaps` times), so
    one mis-tagged lead no longer sinks the whole niche claim — the claim just
    drops that lead and keeps the rest. Returns None (-> generalist) only if no
    all-fitting niche gift can be assembled. A non-fitting lead is NEVER listed,
    so the 'Power CFO bug' guarantee (never claim a niche a lead contradicts)
    still holds — we drop the lead, not the honesty check."""
    excluded: list[str] = []
    for _ in range(max_swaps + 1):
        trial.sent_lead_ids = list(excluded)
        g = single_kind_gift(trial, scraper, niche_only=True, pack=pack,
                             build=build_gift)                # GATE B (taxonomy)
        if g is None or not g.all_niche:
            return None
        verdicts = fit(label, g.leads)                               # GATE B (genuine fit)
        if not verdicts:
            return None
        if all(verdicts):
            return g
        if not any(verdicts):
            return None      # not one lead reads as the niche: swapping won't change that
        bad = [lead.id for lead, ok in zip(g.leads, verdicts) if not ok]
        if not bad:
            return None
        excluded.extend(bad)                                         # swap the mis-tagged lead(s) out
    return None


def resolve_gift(
    research: ResearchResult, row: dict[str, Any], scraper: _Scraper,
    *, fit: FitFn | None = None, pack: NichePack | None = None,
    claim: ClaimFn | None = None,
) -> tuple[Prospect, Gift | None]:
    """Pick the tier and build the gift. Returns (final_prospect, gift). A niche
    is claimed only if it passes BOTH gates:
      * GATE B (taxonomy): build_gift(niche_only) yields an all_niche gift, AND
      * GATE B (fit): every gift lead's value_prop genuinely reads as the niche
        (`fit`, an LLM check by default — an IT lead mis-tagged manufacturing
        fails here, so the false "you work with manufacturing" claim is dropped).
    Among candidates that pass both, claim the best-supplied one; otherwise drop
    to an honest generalist geo gift. The claimed candidate's own phrase is set
    on the prospect so the review card can't contradict itself."""
    # The claim check runs with the real fit check; a test that injects its
    # own `fit` judges leads only, unless it injects `claim` too.
    claim = claim or (claim_check if fit is None else (lambda phrase, label, listed: True))
    listed = tuple(dict.fromkeys(research.candidate_phrases or []))
    fit = fit or fit_check
    pack = pack or default_pack()
    rank = dict(pack.signal_rank)

    # Gate B's fit check is the only per-prospect LLM cost in the system, and
    # it multiplies: one call per swap attempt (up to `max_swaps` + 1) for EVERY
    # candidate vertical a firm states. A firm naming six industries could
    # therefore cost 24 calls before a single email is written. Capped and
    # counted so the spend is bounded and visible rather than discovered on a
    # bill. The cap is on CANDIDATES, not swaps: the swap loop is what makes a
    # claim honest, while the fifth candidate vertical is a firm listing
    # everything it has ever touched.
    fit_calls = 0

    def counting_fit(label: str, leads: list[Lead]) -> list[bool]:
        nonlocal fit_calls
        fit_calls += 1
        return fit(label, leads)

    best: tuple[Gift, tuple[str, str], str, tuple] | None = None
    candidates_tried = 0
    for mp, phrase in _candidate_pairs(research):
        if candidates_tried >= MAX_FIT_CANDIDATES or fit_calls >= MAX_FIT_CALLS:
            log.info("gift: stopping at %d candidate vertical(s), %d fit check(s)",
                     candidates_tried, fit_calls)
            break
        label = niche_display(mp)
        if not label:
            continue                                             # no clean word -> can't claim honestly
        trial = _base_prospect(row, research, classification="niched", match_param=mp)
        # Supply first, without the model: a vertical with no local all-niche
        # gift does not use up a candidate place.
        supply = build_gift(trial, scraper, niche_only=True, pack=pack)
        if supply is None or not supply.all_niche:
            continue
        # The firm's own words must say it serves this industry.
        if not claim(phrase, label, listed):
            log.info("gift: %r does not say the firm serves %s", phrase, label)
            continue
        candidates_tried += 1
        # GATE B (taxonomy + fit), swapping out any non-fitting lead (niche-lift):
        g = _fitting_niche_gift(trial, scraper, pack, fit_label(mp, label, phrase), counting_fit)
        if g is None:
            # 2026-11-13, the user: when the firm's exact words fail ("framing,
            # sheetrock and painting subcontractors"), fall back to the broad
            # industry (construction) rather than drop the industry line.
            broad = _broad(mp)
            if broad is not None and (blabel := niche_display(broad)) \
                    and fit_calls < MAX_FIT_CALLS and claim(phrase, blabel, listed):
                btrial = _base_prospect(row, research, classification="niched", match_param=broad)
                g = _fitting_niche_gift(btrial, scraper, pack, blabel, counting_fit)
                if g is not None:
                    mp, label = broad, blabel
        if g is None:
            continue                                             # no all-fitting niche gift -> drop
        # 2026-11-12, the user: the industry the firm stresses most, not the
        # one we hold most leads for. Research lists the candidates most
        # stressed first (research.classifier.by_emphasis), so the first that
        # fills a FULL fitting gift is claimed; one that fills only part of a
        # gift is kept as the fallback in case none fills it all.
        if best is None or (best[0].gift_size < GIFT_TARGET <= g.gift_size):
            best = (g, mp, phrase, ())
        if g.gift_size >= GIFT_TARGET:
            break

    if fit_calls:
        log.info("gift: %d fit check(s) across %d candidate vertical(s)",
                 fit_calls, candidates_tried)

    if best is not None:
        gift, mp, phrase, _ = best
        candidates = research.candidate_match_params
        if research.niche_source == "client_list":
            exclusivity = "sole"                                 # client list = sole focus
        elif research.exclusivity == "multiple" or len(candidates) >= 2:
            exclusivity = "one_of_several"
        else:
            exclusivity = "sole"
        prospect = _base_prospect(
            row, research, classification="niched",
            match_param=mp, niche_exclusivity=exclusivity,
        )
        prospect.niche_phrase = phrase                           # the CLAIMED niche's phrase
        return prospect, gift

    # Tier 3 — generalist. No industry claimed; the stated phrase stays saved.
    prospect = _base_prospect(
        row, research, classification="generalist",
        match_param=None, niche_exclusivity="none",
    )
    return prospect, single_kind_gift(prospect, scraper, pack=pack, build=build_gift)
