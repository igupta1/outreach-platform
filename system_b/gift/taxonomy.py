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
    # 2026-11-02, for the sources wired in that day (Restaurants, TexasPermits,
    # Regulated, HomeServices, Community, Professional, church 990-Ts). The
    # niche words the verticals/ folders carry ("faith-based", "catering",
    # "it-services", ...) came from the model's one-word `guess` or a verbatim
    # phrase; every one must reach the taxonomy key the new leads carry
    # (`test_new_niche_words`). Keys are STEMMED words (see `_stem`).
    "faith": ("nonprofit", "religious"), "church": ("nonprofit", "religious"),
    "churche": ("nonprofit", "religious"), "congregation": ("nonprofit", "religious"),
    "ministry": ("nonprofit", "religious"), "ministrie": ("nonprofit", "religious"),
    "synagogue": ("nonprofit", "religious"), "mosque": ("nonprofit", "religious"),
    "catering": ("hospitality_food", "catering_events"),
    "caterer": ("hospitality_food", "catering_events"),
    "fitness": ("fitness_wellness", None), "wellness": ("fitness_wellness", None),
    "gym": ("fitness_wellness", "gym_studio"), "gyms": ("fitness_wellness", "gym_studio"),
    "yoga": ("fitness_wellness", "gym_studio"), "pilates": ("fitness_wellness", "gym_studio"),
    "lender": ("fintech", "lending"), "mortgage": ("fintech", "lending"),
    "blockchain": ("fintech", "crypto_web3"), "bitcoin": ("fintech", "crypto_web3"),
    "attorney": ("professional_services", "law_firm"),
    "lawyer": ("professional_services", "law_firm"),
    "cpa": ("professional_services", "accounting_bookkeeping"),
    "cpas": ("professional_services", "accounting_bookkeeping"),
    "consultant": ("professional_services", "consulting"),
    "msps": ("professional_services", "it_msp"),
    "landscaper": ("home_services", "landscaping"), "lawn": ("home_services", "landscaping"),
    "farm": ("agriculture", None), "farming": ("agriculture", "farming"),
    "agribusiness": ("agriculture", None), "ranch": ("agriculture", None),
    "hoa": ("real_estate", "property_management"), "hoas": ("real_estate", "property_management"),
    "condo": ("real_estate", "property_management"),
    "pool": ("home_services", "pool_services"),
    "childcare": ("education", "childcare_early_ed"), "daycare": ("education", "childcare_early_ed"),
    # 2026-11-04: words firms used on their sites that mapped to nothing
    # ("from HVAC to plumbing", "contractors", "manufacturers", "retailers",
    # "Medical"), so those firms got location-only gifts beside work we have
    # leads for.
    "hvac": ("home_services", "hvac_plumbing_electrical"),
    "plumbing": ("home_services", "hvac_plumbing_electrical"),
    "plumber": ("home_services", "hvac_plumbing_electrical"),
    "electrician": ("home_services", "hvac_plumbing_electrical"),
    "electrical": ("home_services", "hvac_plumbing_electrical"),
    "roofing": ("construction", "specialty_trades"), "roofer": ("construction", "specialty_trades"),
    "contractor": ("construction", None), "demolition": ("construction", None),
    "manufacturer": ("manufacturing", None), "retailer": ("ecommerce_retail", None),
    "medical": ("healthcare", None), "physician": ("healthcare", "medical_practice"),
    "doctor": ("healthcare", "medical_practice"),
}

# A firm's OWN service is not its clients' industry: "a plumber that needs help
# with ongoing bookkeeping" mapped to accounting (2026-11-04, Atlas), which
# would pair an accountant with CPA firms. "accounting" / "bookkeeping" count
# as a served industry only alone (an industries list: "Accounting") or beside
# a word naming the firms that do it ("accounting firms").
_SERVICE_ALIAS_WORDS = frozenset({"accounting", "bookkeeping"})
_SERVICE_AS_CLIENT_RE = re.compile(
    r"\b(?:accounting|bookkeeping)\s+(?:firms?|practices?|offices?|companies|businesses|professionals)\b",
    re.IGNORECASE)

# Multi-word names for a CHILD that no single alias word can say: "it" is not
# a word to alias, "direct to consumer" is three. Same fallback role as
# `_ALIASES` (only when the phrase mapped to nothing), so a real vertical the
# phrase states is never overridden.
_PHRASE_CHILDREN: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bit[\s-]+(?:services?|companies|firms|providers?|support|consulting)\b"
                r"|\bmanaged\s+(?:it\s+)?service\s+providers?\b|\bmsps?\b",
                re.IGNORECASE), "professional_services", "it_msp"),
    (re.compile(r"\bdirect[\s-]to[\s-]consumer\b", re.IGNORECASE),
     "ecommerce_retail", "dtc_brand"),
    (re.compile(r"\bconsumer\s+packaged?\s+goods\b", re.IGNORECASE),
     "ecommerce_retail", "cpg_food_beverage"),
    (re.compile(r"\bfaith[\s-]based\b|\bhouses?\s+of\s+worship\b|\breligious\b",
                re.IGNORECASE), "nonprofit", "religious"),
    (re.compile(r"\bfinancial\s+technology\b", re.IGNORECASE), "fintech", ""),
    (re.compile(r"\b(?:homeowners?|condo(?:minium)?|community)\s+associations?\b"
                r"|\bproperty\s+managers?\b", re.IGNORECASE),
     "real_estate", "property_management"),
    (re.compile(r"\b(?:digital\s+assets?|crypto\s*currenc(?:y|ies))\b", re.IGNORECASE),
     "fintech", "crypto_web3"),
)


# Multi-word names for a parent that has NO children. Government contractors
# are matched at the industry level only: the govcon magnet's leads carry
# `industry=government_contracting` and no niche, so a child token would map a
# prospect to a niche no lead can ever match. These phrases say the parent in
# the trade's own words ("government contractors", "federal contractors",
# "govcon"), where the all-tokens rule needs "government contracting" exactly.
_PHRASE_PARENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:government|federal|gov't|govt)\s+contract(?:or|ors|ing)\b"
                r"|\bgov\s?cons?\b", re.IGNORECASE), "government_contracting"),
)


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
    for rx, parent in _PHRASE_PARENTS:
        if parent in taxonomy and rx.search(phrase or ""):
            found.setdefault(parent, None)
    # Synonym aliases recover a single distinctive industry word (e.g. "saas",
    # "ecommerce") the all-tokens match missed — but ONLY as a fallback when the
    # phrase mapped to nothing. If it already named a real vertical, an alias word
    # is the prospect's own service, not a second served vertical ("managed
    # accounting for dental practices" -> dental, never accounting).
    if not found:
        portfolio_co = bool(_PORTFOLIO_CO_RE.search(phrase or ""))
        for rx, parent, child in _PHRASE_CHILDREN:
            if parent in taxonomy and rx.search(phrase or ""):
                if child and child in taxonomy.get(parent, []):
                    if found.get(parent) is None:
                        found[parent] = child
                else:
                    found.setdefault(parent, None)
        for word in pw:
            if portfolio_co and word in _FUND_SIDE_ALIASES:
                continue
            alias = _ALIASES.get(word)
            if alias is None:
                continue
            # An industry list may say just "Accounting"; a sentence about
            # the firm's own work may not.
            if (word in _SERVICE_ALIAS_WORDS and len(pw) > 2
                    and not _SERVICE_AS_CLIENT_RE.search(phrase or "")):
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


# Words that name no industry at all. When the verbatim phrase is made only of
# these, the model's `guess` must not stand in for it: AP CPA's site said
# "organizations", the model guessed "nonprofit", and the email told them
# "noticed you work with nonprofits" off a word that says nothing of the kind
# (2026-10-24). A guess may only map a phrase that names SOMETHING.
_GENERIC_WORDS = frozenset({
    "organization", "organizations", "org", "orgs", "company", "companies",
    "business", "businesses", "client", "clients", "customer", "customers",
    "firm", "firms", "entity", "entities", "group", "groups", "team", "teams",
    "people", "individual", "individuals", "owner", "owners", "industry",
    "industries", "sector", "sectors", "all", "any", "every", "other", "others",
    "various", "many", "most", "size", "sizes", "type", "types", "kind", "kinds",
    "small", "medium", "mid", "sized", "large", "local", "growing", "and", "or",
    "of", "the", "a", "an", "for", "with", "in", "our", "your", "their",
})


def _names_nothing(phrase: str) -> bool:
    """True when every word in the phrase is generic (or there are none)."""
    words = _WORD_RE.findall((phrase or "").lower())
    return all(w in _GENERIC_WORDS for w in words)


def map_industry_candidates(
    phrase: str, guess: str | None, taxonomy: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """EVERY distinct industry a verbatim phrase states (Change 2), most-specific
    child per parent. "22 dental practices" -> [dental]; a multi-industry phrase
    ("dental practices, construction, real estate") -> [dental, construction,
    real_estate] — all become candidates so the resolver can claim the
    best-supplied, fit-passing one instead of dropping a useful match. Children
    sort first (more specific). Falls back to the model's one-word `guess` only
    when the phrase itself maps to nothing, and never when the phrase names
    nothing ("organizations")."""
    found = _industry_map(phrase, taxonomy)
    out = [_mp_for(parent, child) for parent, child in found.items()]
    if out:
        out.sort(key=lambda mp: 0 if mp[0] == "niche" else 1)   # children first
        return out
    if _names_nothing(phrase):
        return []
    _cls, mp = map_prospect(guess or "", taxonomy)
    return [mp] if mp else []
