"""The accounting niche pack — the CONTROLLER rung of the finance ladder.

Buyer: an outsourced accounting firm. It sells a finance function — the close,
the reporting, a controller — so the gift is companies hiring at that rung, led
by the ones explicitly shopping for a FRACTIONAL controller. That is this
pack's in-market signal, the same shape as a fractional-CFO posting for the cfo
pack.

The junior rung moved to `bookkeeping`. Every word here says "accountant", never
"bookkeeper": accountants treat bookkeeping as a rung below them, and being
addressed as one reads as not having looked. The operator decides which pack a
list belongs to via `--pack`; nothing infers it from a company name.

Vertical-aware with a geo fallback, like every other pack.
"""

from __future__ import annotations

from system_b.copy.email import _cta, framing_line
from system_b.copy.subject import build_who_what
from system_b.gift.engine import _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.niches.base import NichePack

# --- subject voice ---------------------------------------------------------
# Vertical-aware WHO (via build_who_what -> niche_claim, gated on a niched
# prospect) + an accounting-flavored WHAT. Singular WHAT keys off the best
# lead's leadgen signal type; plural WHAT keys off the gift's what_category
# (raised / hiring / mixed).
# The funding rows are gone, not just de-tupled: the EDGAR sources that
# evidenced a raise were deleted, so no funding lead can reach a gift and a
# raise claim is unprovable (see CLAUDE.md). They also outlived the rotation
# removal as 3-tuples, which `build_who_what` no longer unpacks — a funding lead
# would have f-stringed a Python tuple repr straight into a subject line.
_SINGULAR_WHAT = {
    "job_fractional_controller": "is hiring a fractional controller",
    "job_finance_lead": "is hiring a controller",
}
_PLURAL_WHAT = {
    "hiring": "hiring finance help right now",
    "mixed": "that could use accounting help right now",
}


def _accounting_subject(gift: Gift, prospect: Prospect) -> str:
    singular = _SINGULAR_WHAT.get(gift.best_lead.signal_type, "that could use accounting help")
    plural = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return build_who_what(gift, prospect, singular_what=singular, plural_what=plural)


def _accounting_framing(gift: Gift, prospect: Prospect) -> str:
    # One opener for the whole batch — the per-lead lines carry the specifics
    # (a fresh finance hire or a raise), so the framing need stays neutral.
    return framing_line(gift, prospect, need="building out their finance function right now")




ACCOUNTING_PACK = NichePack(
    key="accounting",
    followup_signal="a finance-need signal",
    signal_rank={
        "job_fractional_controller": 0,
        "job_finance_lead": 1,
    },
    # A company shopping for a fractional controller is shopping for exactly
    # what this buyer sells — the same in-market logic cfo gets from a
    # fractional-CFO posting.
    priority_signal="job_fractional_controller",
    raise_signals=frozenset(),   # EDGAR sources deleted — no raise claim is provable
    what_category=_cfo_what_category,     # pure signal logic (raised/hiring/mixed)
    subject=_accounting_subject,
    framing=_accounting_framing,
    cta=_cta,                            # vertical-aware, geo fallback (shared)
    funding_phrase=None,
    priority_flag=None,
    dm_audience="accountants",
    dm_role_singular="a controller role",
    dm_role_plural="controller roles",
)
