"""The bookkeeping niche pack — the JUNIOR rung of the finance ladder.

Buyer: a bookkeeping or outsourced-books firm. Gift: companies that just posted
a bookkeeper, staff accountant, AP/AR clerk, payroll or billing role — a
business standing at the hire-versus-outsource decision, which is the whole of
this firm's sales trigger.

Split from `accounting` (the controller rung) because they are different sales
to different buyers. Two things follow, and both are in the copy:

  * The WORD. "built this one for bookkeepers", never "accountants". Calling a
    CPA a bookkeeper reads as not having looked, and the reverse leaves a
    bookkeeper feeling the email was meant for someone else. The pack decides
    it, and the operator decides the pack by which list they hand to `--pack` —
    nothing infers it from a company name.
  * The MOMENT. This buyer wins on timing rather than on urgency: there is no
    lead-first signal at this rung (see leadgen's `niches/bookkeeping.py` — a
    company that decides to outsource its books simply stops posting), so the
    voice leans on catching the decision as it is being made.

Vertical-aware with a geo fallback, like every other pack: it claims the served
vertical only when `niche_claim` allows it, otherwise it opens on geography.
"""

from __future__ import annotations

from system_b.copy.email import _cta, framing_line
from system_b.copy.subject import build_who_what
from system_b.gift.engine import _cfo_what_category
from system_b.gift.models import Gift, Prospect
from system_b.niches.base import NichePack

# Every lead here is a junior-finance posting, so the singular WHAT names the
# actual seat rather than a generic "finance role" — "a bookkeeper" is the
# recognizable thing to this reader.
_SINGULAR_WHAT = {
    "job_junior_finance": "is hiring a bookkeeper",
}
_PLURAL_WHAT = {
    "hiring": "hiring bookkeeping help right now",
    "mixed": "that could use bookkeeping help right now",
}


def _bookkeeping_subject(gift: Gift, prospect: Prospect) -> str:
    singular = _SINGULAR_WHAT.get(gift.best_lead.signal_type, "is hiring a bookkeeper")
    plural = _PLURAL_WHAT.get(gift.what_category, _PLURAL_WHAT["mixed"])
    return build_who_what(gift, prospect, singular_what=singular, plural_what=plural)


def _bookkeeping_framing(gift: Gift, prospect: Prospect) -> str:
    return framing_line(gift, prospect, need="looking for bookkeeping help right now")




BOOKKEEPING_PACK = NichePack(
    key="bookkeeping",
    followup_signal="a bookkeeping-need signal",
    signal_rank={"job_junior_finance": 0},
    # None, and not for want of looking: outsourced bookkeeping is not a role a
    # company advertises for, so no posting says "in-market" the way a
    # fractional-CFO posting does.
    priority_signal=None,
    raise_signals=frozenset(),   # EDGAR sources deleted — no raise claim is provable
    what_category=_cfo_what_category,     # pure signal logic (raised/hiring/mixed)
    subject=_bookkeeping_subject,
    framing=_bookkeeping_framing,
    cta=_cta,
    funding_phrase=None,
    priority_flag=None,
    dm_audience="bookkeepers",
    dm_role_singular="a bookkeeping role",
    dm_role_plural="bookkeeping roles",
)
