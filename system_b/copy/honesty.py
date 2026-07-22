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

# A "raise" = a SEC funding filing (Form D/C). Copy templates a raise line for
# these (no dollar amount — the filing figure is a target, not money raised).
RAISE_SIGNALS = frozenset({"funding_form_d", "funding_form_c"})

# Currency figures: "$2M", "$1,500,000", "$500k", or bare "2M" / "1.5 million".
_MONEY_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|mm|bn|million|thousand|billion)?"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:k|m|b|mm|bn|million|thousand|billion)\b",
    re.IGNORECASE,
)


def is_raise(lead: Lead, raise_signals: frozenset[str] = RAISE_SIGNALS) -> bool:
    return lead.signal_type in raise_signals


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


# Relative/absolute date phrases a human edit might introduce. We can't know the
# lead's date_confidence from free text, so we WARN (not strip) — dates are only
# safe for high-confidence signals, and the reviewer must confirm.
_DATE_RE = re.compile(
    r"\b(today|yesterday|last week|last month|this week|\d+\s+days?\s+ago"
    r"|\d+\s+weeks?\s+ago|a week ago|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
    re.IGNORECASE,
)


def lint_free_text(text: str) -> tuple[str, list[str]]:
    """Re-run the copy honesty guarantees over human-edited text (build-plan H
    edit action): STRIP any dollar amount (a raise figure is never money raised)
    and WARN on any date phrase (dates are only honest for high-confidence
    signals). Returns (cleaned_text, warnings)."""
    warnings: list[str] = []
    cleaned, stripped = strip_dollar_amounts(text)
    if stripped:
        warnings.append(
            "removed a dollar amount — a raise figure is a filing target, never state it"
        )
    if _DATE_RE.search(cleaned):
        warnings.append(
            "contains a date/recency phrase — only high-confidence signals may carry a "
            "date; verify the lead before sending or remove it"
        )
    return cleaned, warnings
