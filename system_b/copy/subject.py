"""Step 4 — subject line. Pure lookup over the gift, all lowercase.

4a shape is precomputed on the gift (`subject_shape`). 4b is the plural
WHO+WHAT table; 4c is the singular table keyed off the best lead's match
level. `an` before a vowel sound (4c only — plural WHOs take no article).
"""

from __future__ import annotations

from system_b.copy.lex import apply_article, city_display, niche_display, state_display
from system_b.gift.models import Gift, Prospect

# 4b WHAT (plural), first match wins. `what_category` already encodes the
# "double counts as both" rule from the engine.
_PLURAL_WHAT = {
    "raised": "that just raised",
    "hiring": "hiring finance leadership right now",
    "mixed": "that need finance help right now",
}

# 4c WHAT (singular), from the best lead's signal type.
_SINGULAR_WHAT = {
    "cfo_wanted": "is hiring a fractional cfo",
    "double_signal": "just raised",
    "funding_only": "just raised",
    "hiring_only": "is hiring finance leadership",
}


def niche_claim(gift: Gift, prospect: Prospect) -> str | None:
    """The plain-English niche to use in copy, or None to render generalist.
    Gated on BOTH conditions, so copy is honest by construction:
      * gift.all_niche (spec 3e: a gift filled from L4/L5 never mentions the
        niche, even a niched prospect's) AND
      * the token has a curated label (never emit a raw taxonomy token).
    """
    if not gift.all_niche:
        return None
    return niche_display(prospect.match_param)


def _plural_who(gift: Gift, prospect: Prospect) -> str:
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if niche:
        if gift.geo_level == "city":
            return f"{niche} companies in {city}"
        if gift.geo_level == "state":
            return f"{niche} companies in {state}"
        return f"{niche} companies"
    if gift.geo_level == "city":
        return f"companies in {city}"
    if gift.geo_level == "state":
        return f"{state} companies"
    return "companies"


def _singular_who(gift: Gift, prospect: Prospect) -> str:
    lvl = gift.best_lead_level
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    # niche rows only when the niche is actually claimable; otherwise fall to
    # the geography-only WHO by the best lead's match level.
    if niche and lvl == 1:
        who = f"a {niche} company in {city}"
    elif niche and lvl == 2:
        who = f"a {niche} company in {state}"
    elif niche and lvl == 3:
        who = f"a {niche} company"
    elif lvl in (1, 4):          # city match (niched L4 or generalist L1)
        who = f"a company in {city}"
    elif lvl in (2, 5):          # state match (niched L5 or generalist L2)
        who = f"a {state} company"
    else:
        who = "a company"        # niche-only match with no claimable niche
    return apply_article(who)


def build_subject(gift: Gift, prospect: Prospect) -> str:
    if gift.subject_shape == "singular":
        who = _singular_who(gift, prospect)
        what = _SINGULAR_WHAT.get(gift.best_lead.signal_type, "")
    else:
        who = _plural_who(gift, prospect)
        what = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return f"{who} {what}".strip().lower()
