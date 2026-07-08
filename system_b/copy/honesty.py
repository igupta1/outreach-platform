"""Step 5e — copy honesty rules, enforced in code (never left to the LLM).

  * Relative dates are RECOMPUTED from signals[].date, for high-confidence
    signals only, and never copied from plain_words_description.
  * Low-confidence sources (fractionaljobs.io / most cfo_wanted) get NO date.
  * A raise never carries a dollar amount — the filing figure is a target,
    not money raised. Any $-amount the LLM slips in is stripped + flagged.
  * Domainless leads and funding leads driving a city claim get review flags.

The sender (M6) recomputes dates again at actual send time; this module
computes them as of a caller-supplied `today` so drafts and tests are
deterministic.
"""

from __future__ import annotations

import re
from datetime import date

from system_b.models import Lead

RAISE_SIGNALS = frozenset({"funding_only", "double_signal"})

# Currency figures: "$2M", "$1,500,000", "$500k", or bare "2M" / "1.5 million".
_MONEY_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|mm|bn|million|thousand|billion)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|mm|bn|million|thousand|billion)\b",
    re.IGNORECASE,
)


def is_raise(lead: Lead) -> bool:
    return lead.signal_type in RAISE_SIGNALS


def relative_date(iso: str, today: date) -> str:
    """Rough, honest relative date. '' if the date can't be parsed."""
    try:
        d = date.fromisoformat(iso[:10])
    except (ValueError, TypeError):
        return ""
    delta = (today - d).days
    if delta < 0:
        return ""
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta <= 6:
        return f"{delta} days ago"
    weeks = round(delta / 7)
    return "about a week ago" if weeks == 1 else f"about {weeks} weeks ago"


def date_suffix(lead: Lead, today: date) -> str:
    """The relative-date clause for a lead's line, or '' when it must be
    suppressed (low-confidence source, or no usable date)."""
    if lead.effective_date_confidence != "high":
        return ""
    return relative_date(lead.newest_date, today)


def strip_dollar_amounts(text: str) -> tuple[str, bool]:
    """Remove any dollar figure and report whether one was found. Tidies the
    leftover whitespace/punctuation so the sentence still reads."""
    if not _MONEY_RE.search(text):
        return text, False
    cleaned = _MONEY_RE.sub("", text)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)   # " ," -> ","
    cleaned = re.sub(r"\bof\s+(?=[,.;:]|$)", "", cleaned)  # "raise of ," -> "raise ,"
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, True
