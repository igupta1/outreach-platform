"""Step 4 — subject line. Pure lookup over the gift, all lowercase.

4a shape is precomputed on the gift (`subject_shape`). 4b is the plural
WHO+WHAT table; 4c is the singular table keyed off the best lead's match
level. `an` before a vowel sound (4c only — plural WHOs take no article).
"""

from __future__ import annotations

import zlib

from system_b.copy.lex import apply_article, city_display, niche_display, state_display
from system_b.gift.models import Gift, Prospect

# 4b WHAT (plural), first match wins. `what_category` already encodes the
# "double counts as both" rule from the engine.
_PLURAL_WHAT = {
    "raised": "that just raised",
    "hiring": "hiring finance leadership right now",
    "mixed": "that need finance help right now",
}

# 4c WHAT (singular), from the best lead's signal type (leadgen raw vocab). Each
# is a tuple of honest, equivalent phrasings rotated deterministically per
# prospect (`_what_variant`) so a domain isn't sending one identical subject over
# and over — index 0 is the canonical wording. All variants mean the same thing.
_SINGULAR_WHAT = {
    "job_fractional_cfo": (
        "is hiring a fractional cfo",
        "is looking for a fractional cfo",
        "just posted a fractional cfo role",
    ),
    "funding_form_d": ("just raised", "just closed a round", "just landed funding"),
    "funding_form_c": ("just raised", "just closed a round", "just landed funding"),
    "job_finance_lead": (
        "is hiring finance leadership",
        "is building out its finance team",
        "is hiring a finance lead",
    ),
}


def _what_variant(prospect: Prospect, variants: tuple[str, ...]) -> str:
    """Deterministic per-prospect pick from equivalent WHAT phrasings — same
    crc32(firm_name) rotation the 5b left-field lines use, so a redraft is stable
    and tests are reproducible. `crc32('Test Firm') % 3 == 0` keeps fixtures on
    the canonical wording."""
    if not variants:
        return ""
    idx = zlib.crc32(prospect.firm_name.encode("utf-8")) % len(variants)
    return variants[idx]


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
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    # The geographic claim follows the gift as a WHOLE (`gift.geo_level`), NOT the
    # best lead's match level. Keying off the best lead let the subject promise a
    # city ("a healthcare company in new york") while the leads listed in the body
    # spanned other states — the best lead matched the city but the #1 shown lead
    # did not. Mirrors `_plural_who` so singular and plural stay equally honest.
    if niche:
        if gift.geo_level == "city":
            who = f"a {niche} company in {city}"
        elif gift.geo_level == "state":
            who = f"a {niche} company in {state}"
        else:
            who = f"a {niche} company"
    elif gift.geo_level == "city":
        who = f"a company in {city}"
    elif gift.geo_level == "state":
        who = f"a {state} company"
    else:
        who = "a company"
    return apply_article(who)


def _cfo_subject(gift: Gift, prospect: Prospect) -> str:
    """The CFO subject body (the CFO pack's `subject`)."""
    if gift.subject_shape == "singular":
        who = _singular_who(gift, prospect)
        what = _what_variant(prospect, _SINGULAR_WHAT.get(gift.best_lead.signal_type, ()))
    else:
        who = _plural_who(gift, prospect)
        what = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return f"{who} {what}".strip().lower()


def build_who_what(
    gift: Gift,
    prospect: Prospect,
    *,
    singular_what: str | tuple[str, ...],
    plural_what: str | tuple[str, ...],
) -> str:
    """Generic WHO+WHAT subject for the non-CFO packs. Reuses the niche-agnostic
    WHO builders (`_singular_who` / `_plural_who`), which already claim a vertical
    ONLY when the gift is all-niche (via `niche_claim`) and otherwise fall back to
    a geography-only WHO. The pack supplies its own value-prop WHAT — a plain
    string, or a tuple of equivalent phrasings rotated per prospect (same idiom
    as the CFO pack, so a pack's subjects vary across a domain instead of one
    repeated line)."""
    if gift.subject_shape == "singular":
        what = _what_variant(prospect, singular_what) if isinstance(singular_what, tuple) else singular_what
        return f"{_singular_who(gift, prospect)} {what}".strip().lower()
    what = _what_variant(prospect, plural_what) if isinstance(plural_what, tuple) else plural_what
    return f"{_plural_who(gift, prospect)} {what}".strip().lower()


def build_subject(gift: Gift, prospect: Prospect, *, pack: object | None = None) -> str:
    """Dispatch to the niche pack's subject builder (defaults to CFO)."""
    from system_b.niches.base import default_pack

    return (pack or default_pack()).subject(gift, prospect)
