"""Step 4 — subject line. Pure lookup over the gift, all lowercase.

4a shape is precomputed on the gift (`subject_shape`). 4b is the plural
WHO+WHAT table; 4c is the singular table keyed off the best lead's match
level. `an` before a vowel sound (4c only — plural WHOs take no article).
"""

from __future__ import annotations

from system_b.copy.lex import (
    apply_article,
    city_display,
    niche_display,
    niche_noun,
    state_display,
)
from system_b.gift.engine import what_key
from system_b.gift.models import Gift, Prospect

# 4b WHAT (plural), first match wins. `what_category` already encodes the
# "double counts as both" rule from the engine.
_PLURAL_WHAT = {
    "raised": "that just raised",
    "hiring": "hiring finance leadership right now",
    # The magnets. These companies announced nothing — the signal is an
    # ABSENCE read off a filing — so the subject must not imply an event.
    #
    # Each names the DOCUMENT it came from, and that is the positioning, not
    # decoration. Everyone else selling leads to a finance firm scraped a job
    # board; "from their 990s" says in three words that this came out of a
    # filing the recipient can open, which is the only thing that separates
    # this from a list they could build themselves in an afternoon.
    #
    # One category per magnet, because the three do NOT verify the same thing
    # and a shared phrase made one of them false. The Nonprofit and Ecommerce
    # filters both confirm no finance staff; the FUNDS filter does not — it
    # checks unadministered funds, investor counts and headcount, and a
    # 15-person adviser may well employ a controller.
    "unstaffed_funds": "running funds with no administrator, from their adv",
    "unstaffed_ecommerce": "with nobody in finance",
    "unstaffed": "with nobody running finance",
    "mixed": "that need finance help right now",
}

# The lead inventory's record-based signals, shared by every pack: none says
# "accountant" or "bookkeeper", so each pack's subject can use them as-is.
# Each states the EVENT the record shows; none is "hiring" or "raised", and
# none carries a date or a figure.
RECORD_PLURAL_WHAT: dict[str, str] = {
    "davis_bacon": "on federal jobs with weekly certified payroll",
    "new_license": "with a new contractor license",
    "license_upgrade": "moving up to a bigger contractor license",
    "auditable_contract": "on federal contracts the government can audit",
    "first_grant": "with their first federal grant in 3+ years",
    # Charities whose auditors flagged their controls or grant handling.
    "nonprofit_audit": "whose auditors flagged problems",
    "new_business": "newly registered with the state",
    # A gift mixing record kinds (or one with an absence magnet).
    "public_record": "that need finance help, from public records",
}
RECORD_SINGULAR_WHAT: dict[str, str] = {
    "construction_federal_award_davis_bacon": "won a federal job with weekly certified payroll",
    "construction_new_licensed_business": "has a new contractor license",
    "construction_license_upgrade": "moved up to a bigger contractor license",
    "federal_cost_reimbursement_contract": "won a federal contract the government can audit",
    "federal_first_time_grant": "got its first federal grant in 3+ years",
    "new_business_formed": "is newly registered with the state",
    # Charities, by what their federal audit shows (gift.engine.what_key).
    "nonprofit_audit_finding": "whose auditors flagged problems",
    "nonprofit_record": "needs finance help, from public records",
}
_PLURAL_WHAT.update(RECORD_PLURAL_WHAT)

# 4c WHAT (singular), from the best lead's signal type (leadgen raw vocab). One
# phrasing each: the equivalent variants this used to rotate through were the
# same sentence said five ways, and picking between them by a hash of the firm
# name bought variety nobody could act on while making the copy harder to reason
# about. The subject already varies per prospect through the WHO — their city,
# their vertical, the lead's role.
_SINGULAR_WHAT = {
    "job_fractional_cfo": "is hiring a fractional cfo",
    "funding_form_d": "just raised",
    "funding_form_c": "just raised",
    "job_finance_lead": "is hiring finance leadership",
    # Magnet singulars. Each states the absence the filing shows, in the
    # plainest words, with no figure the recipient cannot check in one click.
    "adv_no_fund_administrator": "runs funds with no administrator",
    "ecommerce_sku_load_no_finance_staff": "has nobody in finance",
}
_SINGULAR_WHAT.update(RECORD_SINGULAR_WHAT)


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


def lead_noun(gift: Gift, n: int = 2) -> str:
    """What to call the gift's leads when no vertical is claimed: "nonprofits"
    when every lead is one (a charity is not a company), else "companies".
    Describes the LEADS, so it is no claim about whom the prospect serves."""
    if gift.leads and all(ld.industry == "nonprofit" for ld in gift.leads):
        return "nonprofit" if n == 1 else "nonprofits"
    return "company" if n == 1 else "companies"


def _plural_who(gift: Gift, prospect: Prospect) -> str:
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if niche:
        if gift.geo_level == "city":
            return f"{niche_noun(niche)} in {city}"
        if gift.geo_level == "state":
            return f"{niche_noun(niche)} in {state}"
        return niche_noun(niche)
    things = lead_noun(gift)
    if gift.geo_level == "city":
        return f"{things} in {city}"
    if gift.geo_level == "state":
        return f"{state} {things}"
    return things


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
            who = f"a {niche_noun(niche, 1)} in {city}"
        elif gift.geo_level == "state":
            who = f"a {niche_noun(niche, 1)} in {state}"
        else:
            who = f"a {niche_noun(niche, 1)}"
    elif gift.geo_level == "city":
        who = f"a {lead_noun(gift, 1)} in {city}"
    elif gift.geo_level == "state":
        who = f"a {state} {lead_noun(gift, 1)}"
    else:
        who = f"a {lead_noun(gift, 1)}"
    return apply_article(who)


def _cfo_subject(gift: Gift, prospect: Prospect) -> str:
    """The CFO subject body (the CFO pack's `subject`)."""
    if gift.subject_shape == "singular":
        who = _singular_who(gift, prospect)
        what = _SINGULAR_WHAT.get(what_key(gift.best_lead), "")
    else:
        who = _plural_who(gift, prospect)
        what = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return f"{who} {what}".strip().lower()


def build_who_what(
    gift: Gift,
    prospect: Prospect,
    *,
    singular_what: str,
    plural_what: str,
) -> str:
    """Generic WHO+WHAT subject for the non-CFO packs. Reuses the niche-agnostic
    WHO builders (`_singular_who` / `_plural_who`), which already claim a vertical
    ONLY when the gift is all-niche (via `niche_claim`) and otherwise fall back to
    a geography-only WHO. The pack supplies its own value-prop WHAT — a plain
    string, or a tuple of equivalent phrasings rotated per prospect (same idiom
    as the CFO pack, so a pack's subjects vary across a domain instead of one
    repeated line)."""
    if gift.subject_shape == "singular":
        return f"{_singular_who(gift, prospect)} {singular_what}".strip().lower()
    return f"{_plural_who(gift, prospect)} {plural_what}".strip().lower()


# --- the short subject (2026-10-25) ------------------------------------------
#
# "nonprofits in florida that need finance help, from public records" is cut
# off on a phone. A finance pack whose gift is all inventory records now gets
# "{n} {place} {what they are} {what the record shows}", under ~45 characters:
#
#   3 atlanta nonprofits with audit problems
#   3 california contractors on federal jobs
#
# The noun says what the LEADS are ("contractors", not the prospect's niche
# label), so it is no claim about whom the prospect serves.
_SHORT_WHAT: dict[str, str] = {
    "nonprofit_audit": "with audit problems",
    "davis_bacon": "on federal jobs",
    "auditable_contract": "with auditable federal contracts",
    "first_grant": "with new federal grants",
    "new_license": "with new contractor licenses",
    "license_upgrade": "moving up a contractor license",
    "new_business": "that just registered",
    "public_record": "that need finance help",
}
_SHORT_WHAT_ONE: dict[str, str] = {
    "nonprofit_audit": "with audit problems",
    "davis_bacon": "on a federal job",
    "auditable_contract": "with an auditable federal contract",
    "first_grant": "with a new federal grant",
    "new_license": "with a new contractor license",
    "license_upgrade": "moving up a contractor license",
    "new_business": "that just registered",
    "public_record": "that needs finance help",
}
_CONTRACTOR_KINDS = frozenset({"davis_bacon", "auditable_contract", "new_license",
                               "license_upgrade"})
_FINANCE_PACK_KEYS = frozenset({"cfo", "accounting", "bookkeeping", "finance"})


def short_subject(gift: Gift, prospect: Prospect) -> str | None:
    """The phone-length subject for a record gift, or None (keep the pack's)."""
    from system_b.copy.email import _RECORD_FAMILY

    if not gift.leads or any(ld.signal_type not in _RECORD_FAMILY for ld in gift.leads):
        return None
    kind = gift.what_category
    if kind not in _SHORT_WHAT:
        kind = "public_record"
    n = gift.gift_size
    if kind in _CONTRACTOR_KINDS:
        noun = "contractor" if n == 1 else "contractors"
    else:
        noun = lead_noun(gift, n)
    place = (city_display(prospect.city) if gift.geo_level == "city"
             else state_display(prospect.state) if gift.geo_level == "state" else "")
    what = (_SHORT_WHAT_ONE if n == 1 else _SHORT_WHAT)[kind]
    head = " ".join(w for w in (place, noun) if w)
    count = apply_article(f"a {head}") if n == 1 else f"{n} {head}"
    return f"{count} {what}".lower()


def build_subject(gift: Gift, prospect: Prospect, *, pack: object | None = None) -> str:
    """Dispatch to the niche pack's subject builder (defaults to CFO); a finance
    pack's record gift gets the short subject."""
    from system_b.niches.base import default_pack

    pack = pack or default_pack()
    if getattr(pack, "key", None) in _FINANCE_PACK_KEYS:
        short = short_subject(gift, prospect)
        if short:
            return short
    return pack.subject(gift, prospect)
