"""The accounting / bookkeeping niche pack.

Buyer: an accounting or bookkeeping firm. Gift: small companies that just posted
a finance role (finance lead or a junior finance hire — bookkeeper, staff
accountant, AP/AR clerk) or that just raised — companies with a finance need that
haven't committed to an in-house finance department yet, i.e. the outsource
window.

Unlike the geo-only trucking/legacy-bookkeeping shape, the copy here is
VERTICAL-AWARE with a geo fallback: it claims the firm's served vertical only
when the prospect is `niched` (via the shared `niche_claim` gate in the copy
scaffolding), otherwise it opens on the prospect's city/state. This mirrors the
CFO pack; the accounting voice is the only difference. Adaptation of leadgen
inventory rows onto the outreach `Lead` lives in `clients/inventory.py`.
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
_SINGULAR_WHAT = {
    "funding_form_d": ("just raised", "just closed a round", "just landed funding"),
    "funding_form_c": ("just raised", "just closed a round", "just landed funding"),
    "job_finance_lead": (
        "is hiring finance help",
        "is building out its finance function",
        "is bringing on finance help",
    ),
    "job_junior_finance": (
        "just posted a junior finance role",
        "is hiring junior finance",
        "just opened a junior finance seat",
    ),
}
_PLURAL_WHAT = {
    "raised": ("that just raised", "that just closed a round", "that just landed funding"),
    "hiring": (
        "hiring finance help right now",
        "adding finance help right now",
        "bringing on finance help right now",
    ),
    "mixed": (
        "that could use bookkeeping help right now",
        "that could use accounting help right now",
        "showing a bookkeeping need right now",
    ),
}


def _accounting_subject(gift: Gift, prospect: Prospect) -> str:
    singular = _SINGULAR_WHAT.get(gift.best_lead.signal_type, "that could use bookkeeping help")
    plural = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return build_who_what(gift, prospect, singular_what=singular, plural_what=plural)


def _accounting_framing(gift: Gift, prospect: Prospect) -> str:
    # One opener for the whole batch — the per-lead lines carry the specifics
    # (a fresh finance hire or a raise), so the framing need stays neutral.
    return framing_line(gift, prospect, need="looking for bookkeeping help right now")


# 5b — left-field rotation, accounting/bookkeeping-firm voice. Lowercase, no em
# dashes; kept EXACTLY as authored.
ACCOUNTING_LEFT_FIELD: tuple[str, ...] = (
    "most accountants i talk to say clients come by referral, till it slows down. "
    "built this to catch companies the week they start hiring finance help.",
    "every bookkeeper i talk to says the same thing, the best clients are the ones "
    "who just realized they need help. so i built a feed that catches them the day "
    "they post a finance role.",
    "most accounting firms i know wait for the referral. built this to surface "
    "companies the moment they post their first finance hire or file to raise.",
    "the accountants i talk to say the hire-vs-outsource moment is the whole game. "
    "so i built a feed that flags companies right when they post a finance role.",
    "most bookkeepers i talk to say timing is everything. built this to catch "
    "companies the week a finance-need signal shows up.",
)
ACCOUNTING_LEFT_FIELD_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")


ACCOUNTING_PACK = NichePack(
    key="accounting",
    followup_signal="a finance-need signal",
    signal_rank={
        "job_finance_lead": 0,
        "job_junior_finance": 0,
        "funding_form_d": 1,
        "funding_form_c": 1,
    },
    priority_signal=None,
    raise_signals=frozenset(),   # EDGAR sources deleted — no raise claim is provable
    what_category=_cfo_what_category,     # pure signal logic (raised/hiring/mixed)
    subject=_accounting_subject,
    framing=_accounting_framing,
    cta=_cta,                            # vertical-aware, geo fallback (shared)
    left_field=ACCOUNTING_LEFT_FIELD,
    left_field_labels=ACCOUNTING_LEFT_FIELD_LABELS,
    funding_phrase=None,
    priority_flag=None,
    dm_audience="accountants",
    dm_role_singular="a finance role",
    dm_role_plural="finance roles",
)
