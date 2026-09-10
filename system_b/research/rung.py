"""Which RUNG of finance service this firm sells — bookkeeping, accounting, or
fractional CFO — read off their own website.

The rung and the vertical are two different questions about the same firm:

    vertical  WHO they serve      nonprofits, e-commerce, funds
    rung      WHAT they sell      bookkeeping, controller work, CFO work

The vertical decides which leads a prospect may be shown. The rung decides one
line of copy: "built this one for fractional cfos" vs "for bookkeepers". It used
to be a single `--pack` flag applied to a whole batch, which is fine for a
single-rung export and wrong for a mixed one — a bookkeeper reading "built this
for fractional cfos" learns immediately that nothing was read about them.

## Why this is keyword matching and not a model

The house rule is that models classify or propose and code verifies. Here there
is nothing for a model to add: the rung is stated in the firm's own service
vocabulary, and that vocabulary is small, stable and unambiguous. "quickbooks
cleanup" is bookkeeping; "fractional cfo" is CFO work. A model would only add a
call, a cost, and a way to be wrong.

## Almost every firm sells more than one rung

That is the normal case, not an edge case: a solo practice will happily do books
AND close the month AND sit in a board meeting. So this does not try to find the
ONE thing they do. It scores the vocabulary of each rung and takes the strongest,
which in practice is the one they lead with on the page.

## The tie-break is deliberately asymmetric

Ties, and near-ties, go to the MORE SENIOR rung. The two errors are not equally
costly: calling a firm that mostly does books a "fractional cfo" reads as
flattery, while calling a fractional CFO a "bookkeeper" reads as an insult and
as evidence that nothing was read. When the page does not settle it, err upward.
"""

from __future__ import annotations

import re

CFO = "cfo"
ACCOUNTING = "accounting"
BOOKKEEPING = "bookkeeping"

# Most senior first. Used for the tie-break and as the confidence order.
SENIORITY: tuple[str, ...] = (CFO, ACCOUNTING, BOOKKEEPING)

# Each rung's own words. Deliberately the service vocabulary a firm uses to
# describe what it SELLS, not general finance nouns — "cash flow" appears on
# every finance site ever written and separates nothing.
_TERMS: dict[str, tuple[str, ...]] = {
    CFO: (
        r"fractional cfo", r"outsourced cfo", r"virtual cfo", r"part[- ]time cfo",
        r"interim cfo", r"cfo services", r"cfo advisory", r"strategic finance",
        r"financial strategy", r"fp&a", r"financial planning (?:and|&) analysis",
        r"board (?:reporting|meetings?|deck)", r"investor reporting",
        r"fundrais\w+ support", r"scenario planning", r"capital strategy",
        r"unit economics", r"exit planning", r"m&a advisory",
    ),
    ACCOUNTING: (
        r"controller", r"outsourced accounting", r"month[- ]end close",
        r"financial statements?", r"gaap", r"accrual accounting",
        r"audit (?:prep|readiness|support)", r"technical accounting",
        r"revenue recognition", r"cost accounting", r"chart of accounts",
        r"consolidat\w+", r"\bcpa\b", r"tax (?:prep|planning|returns?)",
        r"1099", r"financial reporting",
    ),
    BOOKKEEPING: (
        r"bookkeep\w*", r"quickbooks", r"\bxero\b", r"bill\.com", r"gusto",
        r"accounts payable", r"accounts receivable", r"\bap/ar\b",
        r"data entry", r"reconcil\w+", r"catch[- ]?up", r"clean[- ]?up",
        r"payroll (?:processing|services)", r"expense (?:tracking|categoriz\w+)",
        r"transaction categoriz\w+", r"day[- ]to[- ]day (?:books|bookkeeping)",
    ),
}

_COMPILED: dict[str, tuple[re.Pattern[str], ...]] = {
    rung: tuple(re.compile(t, re.IGNORECASE) for t in terms)
    for rung, terms in _TERMS.items()
}

# A rung must clear this many DISTINCT terms before it can win on its own.
# One stray mention of "controller" on a page otherwise about bookkeeping is
# not a controller practice.
MIN_TERMS = 2


def score_rungs(text: str) -> dict[str, list[str]]:
    """{rung: [the distinct phrases that matched, verbatim]}.

    Returns what MATCHED rather than a bare count, so the review card can show
    why a firm was called a bookkeeper and the operator can disagree with the
    evidence in front of them."""
    hits: dict[str, list[str]] = {}
    for rung, patterns in _COMPILED.items():
        found: list[str] = []
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                phrase = m.group(0).strip().lower()
                if phrase not in found:
                    found.append(phrase)
        hits[rung] = found
    return hits


def detect_rung(site: dict[str, str], default: str = CFO) -> tuple[str, list[str]]:
    """(rung, the phrases that decided it).

    `site` is {url: visible_text}, as `research.fetcher` returns it. Falls back
    to `default` when the page says nothing that separates the rungs — which is
    the honest answer for a site that only ever says "accounting services"."""
    text = " ".join(site.values()) if site else ""
    if not text.strip():
        return None, []

    hits = score_rungs(text)
    ranked = sorted(
        SENIORITY,
        key=lambda r: (-len(hits[r]), SENIORITY.index(r)),   # count desc, seniority asc
    )
    best = ranked[0]
    if len(hits[best]) < MIN_TERMS:
        return None, []

    # A near-tie is not a decision. Within one term of the leader, prefer the
    # more senior rung — see the module docstring on asymmetric cost.
    leader_count = len(hits[best])
    contenders = [r for r in SENIORITY if leader_count - len(hits[r]) <= 1
                  and len(hits[r]) >= MIN_TERMS]
    if contenders:
        best = contenders[0]                                  # SENIORITY order
    return best, hits[best]
