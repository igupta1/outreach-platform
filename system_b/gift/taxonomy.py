"""Step 2b — map a prospect's stated focus onto System A's taxonomy.

Deterministic keyword match (no LLM): prefer the most specific granular
child whose tokens all appear in the phrase; else a coarse parent; else
generalist. In production Step 2 [AI] produces a clean phrase; this maps
it. Fetch the live taxonomy from ScraperClient.niches().
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")
_FALLBACK_PARENTS = {"other", "unknown"}


def _words(s: str | None) -> set[str]:
    return set(_WORD_RE.findall((s or "").lower()))


def _token_words(value: str) -> set[str]:
    return {w for w in value.split("_") if w}


def _industry_map(phrase: str, taxonomy: dict[str, list[str]]) -> dict[str, str | None]:
    """{parent_industry: most_specific_child_or_None} for EVERY industry the
    phrase touches (via the parent word or any of its children)."""
    pw = _words(phrase)
    found: dict[str, str | None] = {}
    if not pw:
        return found
    for parent, children in taxonomy.items():
        if parent in _FALLBACK_PARENTS:
            continue
        hit = _token_words(parent) <= pw
        best_child: str | None = None
        best_len = 0
        for child in children:
            if child in _FALLBACK_PARENTS:
                continue
            cw = _token_words(child)
            if cw and cw <= pw:
                hit = True
                if len(cw) > best_len:
                    best_child, best_len = child, len(cw)
        if hit:
            found[parent] = best_child
    return found


def _mp_for(parent: str, child: str | None) -> tuple[str, str]:
    return ("niche", child) if child else ("industry", parent)


def map_prospect(
    phrase: str | None, taxonomy: dict[str, list[str]]
) -> tuple[str, tuple[str, str] | None]:
    """Returns (classification, match_param):
      ("niched", ("niche", child)) | ("niched", ("industry", parent))
      | ("generalist", None)

    A phrase spanning two or more industries collapses to generalist (this is
    the SINGLE-niche mapper used elsewhere; the tiering path uses
    map_industry_candidates to keep every industry as a candidate)."""
    if not phrase:
        return "generalist", None
    found = _industry_map(phrase, taxonomy)
    if len(found) >= 2:
        return "generalist", None
    if len(found) == 1:
        parent, child = next(iter(found.items()))
        return "niched", _mp_for(parent, child)
    return "generalist", None


def map_industry_candidates(
    phrase: str, guess: str | None, taxonomy: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """EVERY distinct industry a verbatim phrase states (Change 2), most-specific
    child per parent. "22 dental practices" -> [dental]; a multi-industry phrase
    ("dental practices, construction, real estate") -> [dental, construction,
    real_estate] — all become candidates so the resolver can claim the
    best-supplied, fit-passing one instead of dropping a useful match. Children
    sort first (more specific). Falls back to the model's one-word `guess` only
    when the phrase itself maps to nothing."""
    found = _industry_map(phrase, taxonomy)
    out = [_mp_for(parent, child) for parent, child in found.items()]
    if out:
        out.sort(key=lambda mp: 0 if mp[0] == "niche" else 1)   # children first
        return out
    _cls, mp = map_prospect(guess or "", taxonomy)
    return [mp] if mp else []
