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

# 4c WHAT (singular), from the best lead's signal type (leadgen raw vocab).
_SINGULAR_WHAT = {
    "job_fractional_cfo": "is hiring a fractional cfo",
    "funding_form_d": "just raised",
    "funding_form_c": "just raised",
    "job_finance_lead": "is hiring finance leadership",
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


def _cfo_subject(gift: Gift, prospect: Prospect) -> str:
    """The CFO subject body (the CFO pack's `subject`)."""
    if gift.subject_shape == "singular":
        who = _singular_who(gift, prospect)
        what = _SINGULAR_WHAT.get(gift.best_lead.signal_type, "")
    else:
        who = _plural_who(gift, prospect)
        what = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return f"{who} {what}".strip().lower()


def build_who_what(
    gift: Gift, prospect: Prospect, *, singular_what: str, plural_what: str
) -> str:
    """Generic WHO+WHAT subject for the non-CFO packs. Reuses the niche-agnostic
    WHO builders (`_singular_who` / `_plural_who`), which already claim a vertical
    ONLY when the gift is all-niche (via `niche_claim`) and otherwise fall back to
    a geography-only WHO. The pack supplies its own value-prop WHAT strings."""
    if gift.subject_shape == "singular":
        return f"{_singular_who(gift, prospect)} {singular_what}".strip().lower()
    return f"{_plural_who(gift, prospect)} {plural_what}".strip().lower()


def build_subject(gift: Gift, prospect: Prospect, *, pack: object | None = None) -> str:
    """Dispatch to the niche pack's subject builder (defaults to CFO)."""
    from system_b.niches.base import default_pack

    return (pack or default_pack()).subject(gift, prospect)
