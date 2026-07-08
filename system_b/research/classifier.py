"""Step 2a classification with the honesty rule enforced IN CODE.

The LLM only *proposes* (niched vs generalist, a stated phrase or a client
list). Code decides: a proposed fact is accepted only if it appears
word-for-word on a fetched page. Anything not verbatim on the site is
dropped, so every fact we save — and therefore every fact copy can later
use — provably exists on the prospect's own site. Hallucinations become
generalist, not false claims.

The niche is then mapped through the SAME taxonomy map as Step 2b (M1). An
unmappable niche is saved as a phrase but classified generalist for
matching (spec 2b: "their phrase stays saved, but ... never claimed").
"""

from __future__ import annotations

import re
from typing import Any, Callable

from system_b.gift.taxonomy import map_prospect
from system_b.research.models import Evidence, ResearchResult

# Below this much total visible text, the site is "thin" -> generalist
# regardless of what the model says (spec 2a rule 3).
THIN_MIN_CHARS = 350
MIN_CLIENTS = 3   # spec 2a rule 2: "3+ named clients"

_WS_RE = re.compile(r"\s+")

# What the injected LLM callable must return (all optional; code re-verifies):
#   {"classification": "niched"|"generalist",
#    "path": "statement"|"client_list",
#    "niche_phrase": "...", "niche_guess": "healthcare",
#    "clients": [{"name": "..."}]}
LlmFn = Callable[[dict[str, str]], dict[str, Any]]


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").lower()).strip()


def appears_verbatim(needle: str, haystack: str) -> bool:
    """Word-for-word match, tolerant only of case + whitespace runs."""
    n = _norm(needle)
    return bool(n) and n in _norm(haystack)


def locate(fact: str, site: dict[str, str]) -> str | None:
    """URL of the first fetched page that contains `fact` verbatim, else None."""
    for url, text in site.items():
        if appears_verbatim(fact, text):
            return url
    return None


def evidence_covers(fact: str, result: ResearchResult) -> bool:
    """The enforcement other layers call before letting a fact into an email:
    the fact must appear word-for-word in saved evidence."""
    return any(appears_verbatim(fact, e.text) for e in result.evidence)


def _generalist(flags: list[str], *, niche_phrase: str | None = None,
                niche_source: str = "", evidence: list[Evidence] | None = None) -> ResearchResult:
    return ResearchResult(
        classification="generalist", match_param=None, niche_phrase=niche_phrase,
        niche_source=niche_source, evidence=evidence or [], flags=flags,
    )


def _map_or_save(phrase: str, taxonomy: dict[str, list[str]], niche_source: str,
                 evidence: list[Evidence], flags: list[str]) -> ResearchResult:
    """Map a verified phrase to the taxonomy. Mapped -> niched. Unmappable
    -> generalist for matching, but keep the phrase + evidence on record."""
    _cls, match_param = map_prospect(phrase, taxonomy)
    if match_param is not None:
        return ResearchResult("niched", match_param, phrase, niche_source, evidence, flags)
    flags.append(f'stated niche "{phrase}" has no taxonomy match — saved, never claimed')
    return _generalist(flags, niche_phrase=phrase, niche_source=niche_source, evidence=evidence)


def classify(
    site: dict[str, str],
    taxonomy: dict[str, list[str]],
    *,
    llm: LlmFn,
) -> ResearchResult:
    """Classify a fetched site. `site` is {url: visible_text}; `llm` proposes,
    code verifies. Deterministic given the same `site` and `llm` output."""
    flags: list[str] = []

    total = sum(len(t) for t in site.values())
    if total < THIN_MIN_CHARS:
        return _generalist(["thin website — generalist fallback"])

    raw = llm(site) or {}
    if raw.get("classification") != "niched":
        return _generalist(flags)

    path = raw.get("path")

    if path == "client_list":
        verified: list[Evidence] = []
        for c in raw.get("clients") or []:
            name = str((c or {}).get("name", "")).strip()
            url = locate(name, site) if name else None
            if url:
                verified.append(Evidence("client", name, url))
        if len(verified) < MIN_CLIENTS:
            flags.append(
                f"client-list evidence insufficient ({len(verified)} verified "
                f"< {MIN_CLIENTS}) — generalist"
            )
            return _generalist(flags)
        # Presence-only: names are verbatim on the page, but we do NOT confirm
        # they're shown AS clients (vs logos/partners/competitors) or are SMBs.
        # So a client-list niche ALWAYS gets a mandatory human review flag before
        # copy can imply "you've worked with a bunch of X".
        flags.append(
            "client-list niche is presence-only — verify these are real clients "
            "(not footer logos / partners / competitors) and SMBs before approving"
        )
        guess = str(raw.get("niche_guess", "")).strip()
        return _map_or_save(guess, taxonomy, "client_list", verified, flags)

    if path == "statement":
        phrase = str(raw.get("niche_phrase", "")).strip()
        url = locate(phrase, site) if phrase else None
        if not url:
            flags.append(
                "stated niche not found verbatim on the site — generalist "
                "(unsupported claim rejected)"
            )
            return _generalist(flags)
        return _map_or_save(phrase, taxonomy, "site", [Evidence("phrase", phrase, url)], flags)

    flags.append("model proposed niched with no usable evidence path — generalist")
    return _generalist(flags)
