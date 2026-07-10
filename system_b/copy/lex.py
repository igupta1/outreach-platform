"""Plain-English display of taxonomy tokens, cities, states, and the
`a`/`an` article. Everything the subject and template render is lowercase
casual voice; company names are the only thing kept verbatim (elsewhere).
"""

from __future__ import annotations

import re

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
    # --- parents (coarse industry) ---
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
    "fitness_wellness": "fitness & wellness",
    "media_entertainment": "media",
    "education": "education",
    "energy": "energy",
    "agriculture": "agriculture",
    "nonprofit": "nonprofit",
    "cannabis": "cannabis",
    # --- children (granular) — category-adjective forms that read as
    # "[label] companies". Tune these as niches surface on real calls;
    # "other"/"unknown" are deliberately absent -> generalist copy.
    "b2b_saas": "b2b software", "consumer_app": "consumer app", "ai_ml": "ai",
    "devtools_infra": "developer tools", "vertical_saas": "vertical software",
    "hardware_iot": "hardware",
    "payments": "payments", "lending": "lending", "wealth_investing": "wealth management",
    "insurtech": "insurtech", "crypto_web3": "crypto", "banking_infra": "banking",
    "dtc_brand": "dtc", "cpg_food_beverage": "cpg", "apparel_fashion": "apparel",
    "beauty_personal_care": "beauty", "brick_mortar_retail": "retail", "marketplace": "marketplace",
    "medical_practice": "medical practice", "dental": "dental", "veterinary": "veterinary",
    "behavioral_mental_health": "behavioral health", "biotech_pharma": "biotech",
    "medical_devices": "medical device", "digital_health": "digital health", "senior_care": "senior care",
    "law_firm": "legal", "accounting_bookkeeping": "accounting",
    "marketing_creative_agency": "creative agency", "consulting": "consulting",
    "staffing_hr": "staffing", "it_msp": "it services", "architecture_engineering": "architecture & engineering",
    "industrial_mfg": "industrial", "consumer_goods_mfg": "consumer goods",
    "food_manufacturing": "food manufacturing", "aerospace_defense": "aerospace & defense",
    "electronics_mfg": "electronics", "chemicals_materials": "chemicals",
    "general_contractor": "construction", "specialty_trades": "specialty trades",
    "homebuilder_developer": "homebuilding", "civil_infrastructure": "civil infrastructure",
    "hvac_plumbing_electrical": "home services", "cleaning_janitorial": "cleaning",
    "landscaping": "landscaping", "pest_control": "pest control", "security_services": "security",
    "property_management": "property management", "real_estate_investment": "real estate",
    "brokerage": "real estate brokerage", "proptech": "proptech",
    "trucking_freight": "trucking", "last_mile_delivery": "delivery",
    "supply_chain_3pl": "logistics", "fleet_services": "fleet",
    "restaurant": "restaurant", "hotel_lodging": "hospitality", "catering_events": "catering",
    "bar_brewery": "beverage", "food_service": "food service",
    "gym_studio": "fitness", "spa_wellness": "wellness", "health_coaching": "health coaching",
    "content_creator": "creator", "production_studio": "production", "gaming": "gaming",
    "publishing": "publishing", "music_events": "events",
    "k12_school": "k-12 education", "higher_ed": "higher education", "edtech": "edtech",
    "training_bootcamp": "training",
    "oil_gas": "oil & gas", "renewables_solar": "solar", "utilities": "utilities", "cleantech": "cleantech",
    "farming": "farming", "agtech": "agtech", "food_production": "food production",
    "charity_foundation": "nonprofit", "religious": "faith-based",
    "membership_association": "membership", "social_services": "social services",
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

# Vowel-letter words with a CONSONANT sound -> take "a" (e.g. "a utah company",
# not "an utah"). And consonant-letter words with a VOWEL sound -> take "an".
# Scoped to what our state/niche vocab can actually hit.
_A_EXCEPTIONS = frozenset({
    "utah", "european", "university", "unicorn", "union", "unique",
    "unified", "user", "unit", "one", "once", "us", "usa",
})
_AN_EXCEPTIONS = frozenset({"hour", "honest", "honor", "honorable", "heir"})


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


def _article_for(word: str) -> str:
    """'a' or 'an' for the word that follows, honoring the sound exceptions."""
    w = word.lower().strip("(\"'").strip(".,;:)\"'")
    if w in _A_EXCEPTIONS:
        return "a"
    if w in _AN_EXCEPTIONS:
        return "an"
    return "an" if w[:1] in _VOWELS else "a"


def apply_article(who: str) -> str:
    """`a` -> `an` before a vowel sound. `who` is a singular WHO that starts
    with 'a ' (e.g. 'a ecommerce company in tennessee')."""
    if not who.startswith("a "):
        return who
    rest = who[2:]
    return f"{_article_for(rest.split(' ', 1)[0])} {rest}"


_ARTICLE_RE = re.compile(r"\b(an?) +([a-z][a-z'\-]*)", re.IGNORECASE)


def fix_articles(text: str) -> str:
    """Correct every 'a/an' in freeform text (the LLM lead lines) to match the
    following word's sound. E.g. 'posted a assistant controller' -> 'an'."""
    return _ARTICLE_RE.sub(lambda m: f"{_article_for(m.group(2))} {m.group(2)}", text)
