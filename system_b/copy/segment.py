"""Segment-level market context for a follow-up email.

The problem this solves: every follow-up was "here is one more lead" — the same
value type as email #1, just a smaller portion, which is what makes a follow-up
read as a bump rather than a reason to reply.

This is a DIFFERENT kind of value, and it is scalable in the one way that
matters: it is computed per (state, pack) SEGMENT, not per prospect, so one
calculation serves every prospect in that state. No per-prospect research, no
manual work.

Honesty rules baked in here:

* "came through" is not "were posted". The inventory is a sample of the market,
  never the whole of it, so the line reports what THIS feed saw. Claiming market
  totals would be an overclaim we cannot support.
* A tiny segment says nothing and reads badly ("1 came through in wyoming this
  month"), so below `_MIN_SEGMENT` the line is omitted entirely rather than
  padded.
* Size uses the coarse BAND, not an exact count. Only ~47% of leads carry an
  exact headcount while ~98% carry a band, so counting on the exact number would
  silently describe half the segment. Bands are also the honest resolution: we
  can say "under 50 people" and be right, where "$3M revenue" would be a guess.
"""

from __future__ import annotations

from datetime import date, timedelta

from system_b.copy.lex import state_display
from system_b.models import Lead

# Below this, a count is noise and reads as thin. Omit the line instead.
_MIN_SEGMENT = 5

# The window the line describes. Matches how a reader hears "this month".
_WINDOW_DAYS = 30

# The size line splits on this. 50 is the top of leadgen's "11-50" band, so the
# split lands on a real band boundary instead of cutting one in half — which is
# what lets the claim be exact rather than approximate.
_SMALL_MAX = 50
_SMALL_BANDS = frozenset({"1-10", "11-50"})


def _is_small(lead: Lead) -> bool:
    """True when the company is provably at or under `_SMALL_MAX`.

    Prefers the exact count and falls back to the band. Unknown size counts as
    NOT small — the line states how many we can SHOW are small, so an unsized
    company must not inflate it."""
    if lead.headcount is not None:
        return lead.headcount <= _SMALL_MAX
    return (lead.headcount_band or "") in _SMALL_BANDS


def _recent(lead: Lead, today: date) -> bool:
    try:
        d = date.fromisoformat((lead.newest_date or "")[:10])
    except (ValueError, TypeError):
        return False
    return timedelta(0) <= (today - d) <= timedelta(days=_WINDOW_DAYS)


def segment_line(
    leads: list[Lead], *, state: str | None, today: date, label: str = "",
) -> str:
    """One sentence of market context for the prospect's state, or "" when the
    segment is too thin to say anything worth reading.

    `label` is the plain-English state name for the copy (already lowercased by
    the caller's `state_display`); passing it in keeps this module free of the
    display lexicon.
    """
    if not state or not label:
        return ""
    # Both sides go through `state_display` before comparing. The two sources
    # disagree on format — Apollo gives the prospect "Georgia", leadgen gives the
    # lead "GA" — so a raw string compare matches NOTHING and the feature dies
    # silently with every segment reading as empty.
    want = state_display(state)
    in_segment = [
        lead for lead in leads
        if state_display(lead.state) == want and _recent(lead, today)
    ]
    n = len(in_segment)
    if n < _MIN_SEGMENT:
        return ""
    small = sum(1 for lead in in_segment if _is_small(lead))
    if small:
        return (
            f"{n} came through in {label} this month, {small} at companies "
            f"under {_SMALL_MAX} people."
        )
    return f"{n} came through in {label} this month."
