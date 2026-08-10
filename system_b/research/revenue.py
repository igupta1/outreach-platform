"""Parse a prospect's stated CLIENT revenue range out of their own words.

The second personalization lever. Measured across 102 live prospect sites, 23%
state a usable client-revenue range ("$2M-$50M revenue", "businesses with annual
revenue below $50 million") — versus 1% who state a headcount criterion, which
is why revenue is the one worth having.

Division of labour matches how the niche phrase is handled:

  * the MODEL proposes a verbatim phrase,
  * `classifier` verifies it appears word-for-word on a fetched page (Gate A),
  * and THIS module — code, not a model — reads the numbers out of it.

Parsing in code rather than trusting the model's own min/max matters: the
numbers end up in a sent email, and a model that mis-reads "$50M raised BY our
clients" as "clients doing $50M" would put a false statement about the reader in
front of the reader.

What this range may and may not be used for is decided in copy, not here, but
the rule is worth stating where the data is born: it describes the PROSPECT
("saw you work with $2m-$10m companies"), never the gift. Leadgen publishes no
revenue field, and a probe of 25 real inventory companies found grounded revenue
estimates unusable — 44% "high confidence" answers included a $100M+ figure for
a company with 1-10 employees. So we can say what they told us, and we can never
claim the leads match it.
"""

from __future__ import annotations

import re

# "$2M", "$1.5 million", "$500k", "$1,000,000". The suffix is optional because
# ranges routinely write it once ("$1-$30m").
_MONEY = r"\$\s*(\d[\d,]*(?:\.\d+)?)\s*(k|m|b|mm|bn|thousand|million|billion)?"

_MULT = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
}

# A range: two money tokens joined by a dash or "to". Captures a trailing "+" on
# the upper bound ("$2M to $50M+"), which means open-ended, not a $50M ceiling.
_RANGE_RE = re.compile(
    _MONEY + r"\s*(?:-|–|—|to|through)\s*" + _MONEY + r"\s*(\+?)",
    re.IGNORECASE,
)
_MAX_RE = re.compile(
    r"\b(?:under|below|less\s+than|up\s+to|no\s+more\s+than)\s*" + _MONEY,
    re.IGNORECASE,
)
_MIN_RE = re.compile(
    r"\b(?:over|above|at\s+least|more\s+than|north\s+of|starting\s+at)\s*" + _MONEY
    + r"|" + _MONEY + r"\s*\+",
    re.IGNORECASE,
)

# Below this, the figure is not plausibly an annual-revenue threshold for a
# company — it is a price, a fee, or a savings claim that happened to sit near
# the word "revenue". Rejecting is cheaper than being wrong in a sent email.
_MIN_PLAUSIBLE = 100_000.0
# Above this we are out of SMB territory entirely, so the phrase is almost
# certainly about something else (funds raised, assets under management).
_MAX_PLAUSIBLE = 10_000_000_000.0

# A figure about the FIRM'S OWN track record, not the size of client it serves.
# The prompt already tells the model not to offer these, but a number that ends
# up in a sent email is exactly the wrong place to trust a model's judgement —
# "$360M+ Raised by our clients" parses as a perfectly clean "$360m+" range and
# would have the email tell a solo fractional CFO they work with $360M companies.
_FIRM_STAT_RE = re.compile(
    r"\b(?:raised|saved|managed|generated|delivered|recovered|secured)\b[^.]{0,24}"
    r"\b(?:by|for|our|client|clients|customer|customers)\b"
    r"|\b(?:clients?|customers?)\s+(?:supported|served|helped)\b"
    r"|\bunder\s+management\b|\bassets\s+under\b|\bAUM\b",
    re.IGNORECASE,
)

Range = tuple[float | None, float | None]


def _value(number: str, suffix: str | None) -> float | None:
    try:
        n = float(number.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        return n * _MULT[suffix.lower()]
    return n


def _plausible(v: float | None) -> bool:
    return v is not None and _MIN_PLAUSIBLE <= v <= _MAX_PLAUSIBLE


def parse_revenue_range(phrase: str | None) -> Range | None:
    """(min, max) in dollars — either bound may be None for an open end — or
    None when the phrase states no usable range.

    Conservative by design: anything it cannot read confidently returns None and
    the prospect simply keeps the weaker personalization lever, which is a far
    better failure than a wrong number in an email."""
    if not phrase:
        return None
    text = phrase.strip()
    if _FIRM_STAT_RE.search(text):
        return None

    m = _RANGE_RE.search(text)
    if m:
        lo_n, lo_s, hi_n, hi_s, plus = m.groups()
        hi = _value(hi_n, hi_s)
        # "$1-$30m": the lower bound borrows the upper bound's unit, which is how
        # ranges are actually written. Without this, "$1" parses as one dollar.
        lo = _value(lo_n, lo_s or hi_s)
        if _plausible(lo) and _plausible(hi) and lo <= hi:
            return (lo, None if plus else hi)
        return None

    m = _MAX_RE.search(text)
    if m:
        hi = _value(m.group(1), m.group(2))
        return (None, hi) if _plausible(hi) else None

    m = _MIN_RE.search(text)
    if m:
        # Two alternations, so the groups land in one pair or the other.
        num, suf = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        lo = _value(num, suf)
        return (lo, None) if _plausible(lo) else None

    return None
