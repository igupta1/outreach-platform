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


def map_prospect(
    phrase: str | None, taxonomy: dict[str, list[str]]
) -> tuple[str, tuple[str, str] | None]:
    """Returns (classification, match_param):
      ("niched", ("niche", child)) | ("niched", ("industry", parent))
      | ("generalist", None)
    """
    if not phrase:
        return "generalist", None
    pw = _words(phrase)
    if not pw:
        return "generalist", None

    # Track which distinct parent industries the phrase touches (via the parent
    # word or any of its children) and the single most-specific child overall.
    matched_parents: set[str] = set()
    best_child: str | None = None
    best_len = 0
    for parent, children in taxonomy.items():
        if parent in _FALLBACK_PARENTS:
            continue
        hit = _token_words(parent) <= pw
        for child in children:
            if child in _FALLBACK_PARENTS:
                continue
            cw = _token_words(child)
            if cw and cw <= pw:
                hit = True
                if len(cw) > best_len:
                    best_child, best_len = child, len(cw)
        if hit:
            matched_parents.add(parent)

    # A phrase spanning two or more industries can't be honestly narrowed to
    # one — treat as generalist (keep the leads, drop the false niche claim).
    if len(matched_parents) >= 2:
        return "generalist", None
    if best_child is not None:
        return "niched", ("niche", best_child)
    if len(matched_parents) == 1:
        return "niched", ("industry", next(iter(matched_parents)))
    return "generalist", None
