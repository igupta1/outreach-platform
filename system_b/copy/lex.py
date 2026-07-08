"""Plain-English display of taxonomy tokens, cities, states, and the
`a`/`an` article. Everything the subject and template render is lowercase
casual voice; company names are the only thing kept verbatim (elsewhere).
"""

from __future__ import annotations

# Taxonomy token -> plain-English label used in copy. The spec is explicit:
# `[niche]` is the plain-English focus (dental, healthcare, ecommerce), NOT
# the taxonomy token (ecommerce_retail). Example-verified rows are load-
# bearing (healthcare, construction, ecommerce_retail->ecommerce, dental);
# the rest are sensible defaults, tune as niches surface on real calls.
#
# HARD RULE: this map is the ONLY source of a niche label in copy. A token
# NOT in here renders as GENERALIST copy (see niche_display -> None), never
# as a raw token. So no underscores, no "unknown", no "software_saas" can
# ever reach a subject or framing line. Add a clean label here to enable a
# niche; until then that niche is honest-by-omission.
NICHE_DISPLAY: dict[str, str] = {
    # parents
    "software_saas": "software",
    "fintech": "fintech",
    "ecommerce_retail": "ecommerce",
    "healthcare": "healthcare",
    "professional_services": "professional services",
    "manufacturing": "manufacturing",
    "construction": "construction",
    "home_services": "home services",
    "real_estate": "real estate",
    "logistics_transport": "logistics",
    "hospitality_food": "hospitality",
    "fitness_wellness": "fitness",
    "media_entertainment": "media",
    "education": "education",
    "energy": "energy",
    "agriculture": "agriculture",
    "nonprofit": "nonprofit",
    "cannabis": "cannabis",
    # children (example-verified / clean single-word)
    "dental": "dental",
}

_STATE_FULL: dict[str, str] = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut", "de": "delaware",
    "fl": "florida", "ga": "georgia", "hi": "hawaii", "id": "idaho",
    "il": "illinois", "in": "indiana", "ia": "iowa", "ks": "kansas",
    "ky": "kentucky", "la": "louisiana", "me": "maine", "md": "maryland",
    "ma": "massachusetts", "mi": "michigan", "mn": "minnesota", "ms": "mississippi",
    "mo": "missouri", "mt": "montana", "ne": "nebraska", "nv": "nevada",
    "nh": "new hampshire", "nj": "new jersey", "nm": "new mexico", "ny": "new york",
    "nc": "north carolina", "nd": "north dakota", "oh": "ohio", "ok": "oklahoma",
    "or": "oregon", "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah",
    "vt": "vermont", "va": "virginia", "wa": "washington", "wv": "west virginia",
    "wi": "wisconsin", "wy": "wyoming", "dc": "district of columbia", "pr": "puerto rico",
}

_VOWELS = frozenset("aeiou")


def niche_display(match_param: tuple[str, str] | None) -> str | None:
    """Plain-English niche for the subject/framing/CTA, or None when there
    is no niche OR the token has no curated label. None means: fall back to
    generalist copy. The raw taxonomy token is NEVER returned — that's the
    whole point (no "software_saas" / "unknown" in a sent email)."""
    if not match_param:
        return None
    _kind, token = match_param
    return NICHE_DISPLAY.get(token)


def city_display(city: str | None) -> str:
    return (city or "").strip().lower()


def state_display(state: str | None) -> str:
    """Full lowercase state name. Accepts 'CA' or 'California'."""
    s = (state or "").strip().lower()
    if len(s) == 2:
        return _STATE_FULL.get(s, s)
    return s


def apply_article(who: str) -> str:
    """`a` -> `an` before a vowel sound. `who` is a singular WHO that starts
    with 'a ' (e.g. 'a ecommerce company in tennessee'). Heuristic on the
    first letter of the following word — right for niches and state names."""
    if not who.startswith("a "):
        return who
    rest = who[2:]
    first = rest[:1].lower()
    return ("an " if first in _VOWELS else "a ") + rest
