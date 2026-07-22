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

from typing import Any, Callable

from system_b.copy.lex import niche_display
from system_b.gift.engine import build_gift
from system_b.gift.fit import fit_check
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import NichePack, default_pack
from system_b.research.models import ResearchResult

# Gate B fit-check: (niche_label, leads) -> per-lead booleans. Injectable so
# tests run offline; production passes the real LLM check.
FitFn = Callable[[str, list[Lead]], list[bool]]


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
        sent_lead_ids=list(row.get("sent_lead_ids") or []),
        **kw,
    )


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


def resolve_gift(
    research: ResearchResult, row: dict[str, Any], scraper: _Scraper,
    *, fit: FitFn | None = None, pack: NichePack | None = None,
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
    fit = fit or fit_check
    pack = pack or default_pack()
    rank = dict(pack.signal_rank)

    best: tuple[Gift, tuple[str, str], str] | None = None
    for mp, phrase in _candidate_pairs(research):
        label = niche_display(mp)
        if not label:
            continue                                             # no clean word -> can't claim honestly
        trial = _base_prospect(row, research, classification="niched", match_param=mp)
        g = build_gift(trial, scraper, niche_only=True, pack=pack)  # GATE B (taxonomy)
        if g is None or not g.all_niche:
            continue
        verdicts = fit(label, g.leads)                           # GATE B (genuine fit)
        if not (verdicts and all(verdicts)):
            continue                                             # a lead doesn't read as the niche -> drop
        if best is None or _supply_key(g, rank) > _supply_key(best[0], rank):
            best = (g, mp, phrase)

    if best is not None:
        gift, mp, phrase = best
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
    return prospect, build_gift(prospect, scraper, pack=pack)
