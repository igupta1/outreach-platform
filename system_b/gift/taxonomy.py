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

# Common one-word industry synonyms the strict all-tokens match misses because
# the taxonomy key is multi-word (e.g. "ecommerce" alone never satisfies
# `ecommerce_retail`, which also needs "retail"). Each maps a stemmed phrase word
# to (parent, child|None); every target has a NICHE_DISPLAY label. This only
# widens how a VERBATIM phrase maps to a vertical — Gate A (verbatim) and Gate B
# (lead fit) are unchanged, so the honesty of the final claim is not weakened.
_ALIASES: dict[str, tuple[str, str | None]] = {
    "ecommerce": ("ecommerce_retail", None),
    "commerce": ("ecommerce_retail", None),
    "retail": ("ecommerce_retail", None),
    "dtc": ("ecommerce_retail", "dtc_brand"),
    "d2c": ("ecommerce_retail", "dtc_brand"),
    "cpg": ("ecommerce_retail", "cpg_food_beverage"),
    "saas": ("software_saas", None),
    "software": ("software_saas", None),
    "crypto": ("fintech", "crypto_web3"),
    "web3": ("fintech", "crypto_web3"),
    # Fund managers. Without these a firm whose site says "we serve private
    # equity funds" classifies as generalist and never sees the Funds magnet,
    # because no single token in the phrase is a taxonomy child.
    "pe": ("investment_management", "private_funds"),
    "vc": ("investment_management", "private_funds"),
    "fund": ("investment_management", "private_funds"),
    "funds": ("investment_management", "private_funds"),
    "gp": ("investment_management", "private_funds"),
    "lp": ("investment_management", "private_funds"),
    "ria": ("investment_management", "wealth_advisory"),
    "msp": ("professional_services", "it_msp"),
    "legal": ("professional_services", "law_firm"),
    "accounting": ("professional_services", "accounting_bookkeeping"),
    "bookkeeping": ("professional_services", "accounting_bookkeeping"),
}


def _stem(w: str) -> str:
    """Crude depluralize: drop a trailing 's' on longer words (never '...ss'), so
    a plural phrase word matches a singular taxonomy token ('firms' -> 'firm')."""
    if len(w) >= 5 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _words(s: str | None) -> set[str]:
    return {_stem(w) for w in _WORD_RE.findall((s or "").lower())}


def _token_words(value: str) -> set[str]:
    return {_stem(w) for w in value.split("_") if w}


# "pe", "vc", "fund" and friends map to private_funds — the firms that RUN the
# funds, which is what the Funds magnet's leads are. The same tokens appear in
# phrases naming the exact opposite customer: a company that RECEIVED fund
# money. "PE-backed SaaS companies", "venture-backed startups", "VC portfolio
# companies" are operating businesses, not fund managers.
#
# Both real funds matches in the only batch ever generated were this mistake.
# Accurix Consulting states "PE-Backed SaaS Companies" and Altureon states
# "venture-backed and PE portfolio companies"; both were sent "noticed you work
# with private fund managers" over a list of fund managers. Neither serves one.
# A recipient knows that from the first line, and it is the precise claim the
# evidence rules exist to prevent.
#
# So these kill the fund aliases specifically. They do not touch the rest of
# the mapping: "PE-backed SaaS" still maps to software_saas, which is what that
# firm actually serves.
_PORTFOLIO_CO_RE = re.compile(
    r"\b(?:"
    r"(?:pe|vc|venture|equity|sponsor|investor|institutionally)[\s-]*backed"
    r"|backed\s+(?:by|companies)"
    r"|portfolio\s+(?:co|cos|company|companies)"
    r"|portco"
    r")\b",
    re.I,
)

# Only these aliases are suppressed by the phrases above. "ria" and
# "wealth_advisory" are unaffected: a firm serving RIAs serves the adviser.
_FUND_SIDE_ALIASES = frozenset({"pe", "vc", "fund", "gp", "lp"})


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
    # Synonym aliases recover a single distinctive industry word (e.g. "saas",
    # "ecommerce") the all-tokens match missed — but ONLY as a fallback when the
    # phrase mapped to nothing. If it already named a real vertical, an alias word
    # is the prospect's own service, not a second served vertical ("managed
    # accounting for dental practices" -> dental, never accounting).
    if not found:
        portfolio_co = bool(_PORTFOLIO_CO_RE.search(phrase or ""))
        for word in pw:
            if portfolio_co and word in _FUND_SIDE_ALIASES:
                continue
            alias = _ALIASES.get(word)
            if alias is None:
                continue
            parent, child = alias
            if child is not None and found.get(parent) is None:
                found[parent] = child
            elif child is None:
                found.setdefault(parent, None)
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
