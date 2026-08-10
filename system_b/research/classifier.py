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

from system_b.gift.taxonomy import map_industry_candidates, map_prospect
from system_b.research.models import Evidence, ResearchResult
from system_b.research.revenue import parse_revenue_range

# Below this much total visible text, the site is "thin" -> generalist
# regardless of what the model says (spec 2a rule 3).
THIN_MIN_CHARS = 350
MIN_CLIENTS = 2   # 2+ named clients, verbatim on the site

# Pages that present the names on them AS clients. A name being verbatim on the
# site is NOT enough to call it a client: the same string in a footer, a
# "partners" strip, or an "as seen in" row would make "you worked with X" false.
# Only names found on one of these pages may be NAMED in copy — the taxonomy
# claim itself is unaffected, since that already survives on presence alone plus
# a mandatory human flag.
#
# Matched against the URL, which is where this is cheap and reliable: the
# fetcher already prioritizes exactly these pages when it discovers links, so a
# real client list almost always lands on one (clearview canary's was
# `/clients-contributions`).
_CLIENT_PAGE_KEYWORDS = (
    "client", "customer", "case-stud", "casestud", "case_stud",
    "portfolio", "our-work", "ourwork", "who-we-serve", "whoweserve",
)


def _is_client_page(url: str) -> bool:
    """True when the page URL presents its contents as clients/customers/work."""
    u = (url or "").lower()
    return any(k in u for k in _CLIENT_PAGE_KEYWORDS)

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
                 evidence: list[Evidence], flags: list[str],
                 *, exclusivity: str = "single") -> ResearchResult:
    """Map a verified phrase to the taxonomy. Mapped -> niched. Unmappable
    -> generalist for matching, but keep the phrase + evidence on record."""
    _cls, match_param = map_prospect(phrase, taxonomy)
    if match_param is not None:
        return ResearchResult(
            "niched", match_param, phrase, niche_source, evidence, flags,
            candidate_match_params=[match_param], candidate_phrases=[phrase],
            exclusivity=exclusivity,
        )
    flags.append(f'stated niche "{phrase}" has no taxonomy match — saved, never claimed')
    return _generalist(flags, niche_phrase=phrase, niche_source=niche_source, evidence=evidence)


def _statement_industries(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """The (verbatim_phrase, industry_guess) pairs the model stated. Prefers the
    Change-2 `industries` list (a firm serving several industries); falls back
    to the single niche_phrase/niche_guess shape for older proposals."""
    inds = raw.get("industries")
    out: list[tuple[str, str]] = []
    if isinstance(inds, list):
        for ind in inds:
            if isinstance(ind, str):
                out.append((ind.strip(), ind.strip()))
            elif isinstance(ind, dict):
                out.append((str(ind.get("phrase", "")).strip(),
                            str(ind.get("guess", "")).strip()))
    if out:
        return out
    phrase = str(raw.get("niche_phrase", "")).strip()
    if phrase:
        return [(phrase, str(raw.get("niche_guess", "")).strip())]
    return []


def _attach_revenue(result: ResearchResult, raw: dict[str, Any], site: dict[str, str]) -> None:
    """Verify and attach the stated CLIENT revenue range, if any.

    Applied on EVERY classification path, niched or not, because the biggest win
    is the generalist: a prospect with no claimable vertical currently opens on
    "saw you're based in atlanta", which is an Apollo merge field and proves
    nothing. A verified revenue range proves someone read their site.

    Gate A applies unchanged — the phrase must appear word-for-word on a fetched
    page — and the NUMBERS are then read by code (`parse_revenue_range`), never
    taken from the model. An unverifiable or unparseable statement simply leaves
    the lever off."""
    phrase = str(raw.get("revenue_phrase") or "").strip()
    if not phrase:
        return
    url = locate(phrase, site)
    if url is None:
        return                                  # not verbatim on the site -> drop
    rng = parse_revenue_range(phrase)
    if rng is None:
        return                                  # code could not read a range -> drop
    result.client_revenue = rng
    result.revenue_phrase = phrase
    # Surfaced on the review card with its source URL, like the niche phrase, so
    # the operator checks the sentence rather than the number we derived from it.
    result.evidence.append(Evidence("revenue", phrase, url))


def classify(
    site: dict[str, str],
    taxonomy: dict[str, list[str]],
    *,
    llm: LlmFn,
) -> ResearchResult:
    """Classify a fetched site. `site` is {url: visible_text}; `llm` proposes,
    code verifies. Deterministic given the same `site` and `llm` output."""
    total = sum(len(t) for t in site.values())
    if total < THIN_MIN_CHARS:
        return _generalist(["thin website — generalist fallback"])
    raw = llm(site) or {}
    result = _classify_niche(raw, site, taxonomy)
    _attach_revenue(result, raw, site)
    return result


def _classify_niche(
    raw: dict[str, Any], site: dict[str, str], taxonomy: dict[str, list[str]]
) -> ResearchResult:
    """The niche half of classification (Gate A). Split out so the revenue lever
    can be attached to whichever result this returns, on every path."""
    flags: list[str] = []

    if raw.get("classification") != "niched":
        return _generalist(flags)

    path = raw.get("path")

    if path == "client_list":
        verified: list[Evidence] = []
        for c in raw.get("clients") or []:
            # the model returns client entries as {"name": ...} OR bare strings
            if isinstance(c, str):
                name = c.strip()
            elif isinstance(c, dict):
                name = str(c.get("name", "")).strip()
            else:
                name = ""
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
        # copy can imply "you've worked with X".
        flags.append(
            "client-list niche is presence-only — verify these are real clients "
            "(not footer logos / partners / competitors) and SMBs before approving"
        )
        # Only names on a page that presents them AS clients may be spoken aloud
        # in copy. Everything else still supports the taxonomy claim (which is
        # softer and human-flagged); it just never gets named.
        nameable = [e.text for e in verified if _is_client_page(e.url)]
        guess = str(raw.get("niche_guess", "")).strip()
        result = _map_or_save(guess, taxonomy, "client_list", verified, flags)
        result.nameable_clients = nameable
        return result

    if path == "statement":
        # Change 2: a firm may state SEVERAL served industries. Verify each
        # phrase verbatim (Gate A) and map it; collect every mappable one as a
        # candidate. The tiering resolver later claims the best-supplied one.
        verified_mp: list[tuple[str, str]] = []
        verified_phrases: list[str] = []
        evidence: list[Evidence] = []
        on_site_phrase: str | None = None
        on_site_url: str | None = None
        any_phrase = False
        for phrase, guess in _statement_industries(raw):
            if not phrase:
                continue
            any_phrase = True
            url = locate(phrase, site)
            if not url:
                continue
            if on_site_phrase is None:
                on_site_phrase, on_site_url = phrase, url
            # map the VERBATIM phrase to EVERY industry it states (granular child
            # preferred). A multi-industry phrase yields several candidates; the
            # resolver claims the best-supplied, fit-passing one.
            added = False
            for mp in map_industry_candidates(phrase, guess, taxonomy):
                if mp not in verified_mp:
                    verified_mp.append(mp)
                    verified_phrases.append(phrase)
                    added = True
            if added:
                evidence.append(Evidence("phrase", phrase, url))

        if verified_mp:
            # "multiple" when the model flags several served industries OR more
            # than one distinct industry mapped -> drives one_of_several ("work
            # with"); a single clear focus stays "single" ("focus on").
            multiple = raw.get("focus") == "multiple" or len(verified_mp) >= 2
            return ResearchResult(
                "niched", verified_mp[0], verified_phrases[0], "site", evidence, flags,
                candidate_match_params=verified_mp, candidate_phrases=verified_phrases,
                exclusivity="multiple" if multiple else "single",
            )
        if on_site_phrase is not None:
            # verbatim on the site but no taxonomy match — save it, never claim.
            flags.append(
                f'stated niche "{on_site_phrase}" has no taxonomy match — saved, never claimed'
            )
            return _generalist(
                flags, niche_phrase=on_site_phrase, niche_source="site",
                evidence=[Evidence("phrase", on_site_phrase, on_site_url or "")],
            )
        if any_phrase:
            flags.append(
                "stated niche not found verbatim on the site — generalist "
                "(unsupported claim rejected)"
            )
        else:
            flags.append("model proposed niched with no usable evidence path — generalist")
        return _generalist(flags)

    flags.append("model proposed niched with no usable evidence path — generalist")
    return _generalist(flags)
