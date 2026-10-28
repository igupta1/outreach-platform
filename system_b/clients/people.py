"""Is a lead's name a person's? (2026-10-27)

A person's name is never gifted. The legal-duty sources name organizations,
but some records name a sole proprietor: a Form 5500's plan sponsor can be
"S Sato" or "Tracey A. Keahi CPA" (both reached a Honolulu firm in the first
dry run). The rule is TaxTrouble's (`taxlead/names.py`, vendored here, not
imported): a name with an entity suffix, a business word or a digit is an
organization; one of two to four plain name words, or a professional title on
a name, is a person. A firm named only for its partners ("Kirkpatrick Price")
reads as people too and is dropped: a lost lead costs a swap, never a gift.
"""

from __future__ import annotations

import re

_SUFFIX = re.compile(
    r"\b(?:l\.?\s?l\.?\s?c|l\.?\s?l\.?\s?p|p\.?\s?l\.?\s?l\.?\s?c|inc|incorporated|corp|"
    r"corporation|company|co|ltd|limited|l\.?\s?p|p\.?\s?c|p\.?\s?a|p\.?\s?s|plc|apc|aplc|pbc|psc|pl|lc|lca|apmc|"
    r"nhq)\b\.?",
    re.IGNORECASE)
BUSINESS_WORDS: frozenset[str] = frozenset({
    "the", "of", "town", "county", "city", "borough", "township", "nation", "tribe", "indians", "museum", "ranch",
    "mission", "memorial", "system", "schools", "education", "embassy", "diocese",
    "academy", "accountancy", "accounting", "advisers", "advisors", "advisory", "aerospace", "agency", "america",
    "american", "apartments", "apparel", "appliance", "appliances", "architects", "architecture", "asphalt", "associates",
    "association", "auto", "autobody", "automotive", "autos", "bakery", "bank", "bar", "barber",
    "bbq", "beauty", "biopharma", "bistro", "boutique", "bowling", "brewery", "brewing", "bros",
    "brothers", "buffet", "builders", "building", "burger", "burgers", "cab", "cabinet", "cabinets",
    "cafe", "cantina", "capital", "care", "caregivers", "carpet", "cars", "carwash", "casino",
    "catering", "cellars", "center", "centre", "chiropractic", "church", "cinema", "cleaners", "cleaning",
    "clinic", "club", "coffee", "collective", "college", "collision", "communications", "computer", "computers",
    "concrete", "construction", "constructors", "consultants", "consulting", "contracting", "contractors", "cooperative", "corps",
    "council", "cpas", "credit", "cuisine", "daycare", "deli", "delivery", "demolition", "dental",
    "design", "designs", "development", "digital", "diner", "dispensary", "distillery", "distilling", "distributing",
    "distribution", "distributors", "district", "drilling", "drywall", "eatery", "electric", "electrical", "electronics",
    "energy", "engineering", "enterprise", "enterprises", "entertainment", "equipment", "equity", "estates", "events",
    "excavating", "excavation", "express", "exterminating", "fabrication", "fabricators", "farm", "farms", "fashion",
    "fence", "fencing", "financial", "firm", "fitness", "flooring", "floral", "florist", "food",
    "foods", "foundation", "freight", "fuel", "fund", "funding", "funds", "furniture", "gallery",
    "gaming", "garage", "glass", "global", "golf", "grill", "grille", "grocery", "group",
    "gutter", "gutters", "gym", "hauling", "health", "healthcare", "heating", "holdings", "homes",
    "hospice", "hospital", "hospitality", "hotel", "housing", "hr", "hvac", "imports", "industries",
    "inn", "installation", "installations", "institute", "insurance", "international", "investments", "janitorial", "jewelers",
    "jewelry", "kitchen", "laboratories", "labs", "landscape", "landscaping", "lanes", "laundromat", "laundry",
    "law", "learning", "legal", "limo", "limousine", "liquor", "liquors", "logistics", "lounge",
    "lumber", "machine", "machining", "maintenance", "management", "manor", "manufacturing", "market", "marketing",
    "markets", "mart", "masonry", "mechanical", "media", "medical", "ministries", "ministry", "mortgage",
    "motel", "motors", "moving", "nails", "national", "network", "networks", "nursery", "nursing",
    "opco", "orthodontics", "outlet", "painting", "partners", "partnership", "paving", "pediatrics", "pest",
    "petroleum", "pharma", "pharmacy", "photography", "physicians", "pizza", "pizzeria", "planning", "plaza",
    "plumbing", "pools", "practice", "preservation", "printing", "productions", "products", "propco", "properties",
    "property", "pub", "realty", "recycling", "rehabilitation", "remodeling", "renovations", "rental", "rentals",
    "repair", "resort", "restaurant", "restaurants", "roofing", "sales", "salon", "saloon", "school",
    "sciences", "security", "service", "services", "siding", "software", "solar", "solutions", "spa",
    "spirits", "sports", "staffing", "station", "steel", "store", "stores", "studio", "studios",
    "supplies", "supply", "surgery", "sushi", "systems", "tacos", "taqueria", "tavern", "tax",
    "tech", "technologies", "technology", "telecom", "theater", "theatre", "therapeutics", "tire", "tires",
    "towing", "trading", "transport", "transportation", "trucking", "trust", "union", "university", "ventures",
    "veterinary", "village", "vineyards", "warehouse", "wealth", "welding", "wholesale", "wine", "winery",
    "wines", "wireless", "works", "worldwide", "ymca",
})
# Professional letters after a person's name, and generation marks (which are
# set aside, never evidence: "Breakthrough Phase II" is a program).
_TITLES = frozenset({"md", "dmd", "dds", "do", "dc", "cpa", "esq", "phd", "rn", "dvm", "od",
                     "ea", "cfp", "lpn", "ms", "np", "lcsw", "pharmd"})
_GENERATION = frozenset({"jr", "sr", "ii", "iii", "iv"})
# Single letters that are words or numerals, not someone's initial.
_NOT_INITIALS = frozenset({"a", "i", "v", "x", "n", "r"})      # "Stop N Go", "Kids R Us"
_NAME_WORD = re.compile(r"^[a-z][a-z'\-]*\.?$", re.IGNORECASE)


_LAST_FIRST = re.compile(r"^[a-z'\-]+(?:\s[a-z'\-]+)?,\s*[a-z'\-]+(?:\s+[a-z'\-]+)?(?:\s+[a-z]\.?)?$",
                         re.IGNORECASE)


_TAIL = re.compile(
    r"[\s,]+(?:l\.?\s?l\.?\s?c|l\.?\s?l\.?\s?p|p\.?\s?l\.?\s?l\.?\s?c|inc|incorporated|"
    r"corp|corporation|ltd|limited|p\.?\s?c|p\.?\s?a|p\.?\s?s|apc|aplc|psc|pl|lc|"
    r"apmc)\.?$", re.IGNORECASE)


def looks_like_person(name: str, *, strict: bool = False) -> bool:
    """"S Sato", "S Sato LLC", "Tracey A. Keahi CPA LLC", "Rene S. Mediavillo,
    MD", "Reeves, Richard Gordon" -> True; "Roth & Company", "Chickasaw
    Nation", "Visa" -> False.

    A legal form after a person's name ("S SATO LLC") still prints a person's
    name once the form is dropped, so it is set aside first. Without `strict`
    two to four plain words are a person only with an INITIAL, a professional
    title or the "LAST, FIRST" shape: an organization name with no suffix
    ("City of Adel", "Nation's Finest") is normal in most sources. `strict`
    (Form 5500 sponsors, which include individuals named plainly: "KREYNE
    SATO") reads ANY two or three plain words as a person, TaxTrouble's rule;
    it also drops a firm named for its partners ("Kirkpatrick Price")."""
    text = (name or "").strip(' "')
    had_tail = False
    while _TAIL.search(text):
        text, had_tail = _TAIL.sub("", text).strip(" ,"), True
    if not text or _SUFFIX.search(text) or re.search(r"\d", text):
        return False
    tokens = [t for t in re.split(r"[\s,]+", text) if t]
    if any(t.strip(".&'\"()").lower() in BUSINESS_WORDS for t in tokens):
        return False
    if re.search(r"\bdo not use\b", text, re.IGNORECASE):
        return True                            # a filer's placeholder, not an organization
    # A title counts after a name only ("DO Not Use" / "Do Good" open on a word).
    titled = any(t.strip(".").lower() in _TITLES for t in tokens[1:])
    words = [tokens[0], *(t for t in tokens[1:]
                          if t.strip(".").lower() not in _TITLES | _GENERATION)]
    if not 2 <= len(words) <= 4 or not all(_NAME_WORD.match(w) for w in words):
        return False
    letters = [w for w in words if len(w.strip(".")) == 1]
    if len(letters) > 1 or len(words) - len(letters) < 1:
        return False                           # "T R V", "C Y F S": initialisms
    if strict and not had_tail and len(words) <= 3:
        return True
    initial = any(w.strip(".").lower() not in _NOT_INITIALS for w in letters)
    return titled or initial or bool(_LAST_FIRST.match(text))
