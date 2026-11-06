"""The offer, the ask and the closing lines (2026-11-05, the user).

The old ask ("worth a look? happy to set it up for you either way :)") named
no offer: "set it up" read as software to install, and the reader could not
tell what saying yes meant. Now every email states ONE offer, free weekly
leads in their niche for two weeks, then they decide, and asks for one small
reply. No price: that is for a call.

2026-11-06, the user: one call to action for now, A ("just reply yes").
B (asking what kind of client) stays written but is not used: `ACTIVE`
holds the variants in play, and the batch CSV still carries `variant`.

The other fixed sentences (the engineer line, email 2's question, email 3)
come in a few equivalent wordings picked by a hash of the prospect's email,
so 200 emails a day do not share six identical sentences (spam filters read
sameness).
"""

from __future__ import annotations

import hashlib

CTA_VARIANTS = ("A", "B")
ACTIVE = ("A",)


def _pick(key: str | None, salt: str, n: int) -> int:
    """A stable choice among `n` wordings for this prospect; the first with no
    key (tests and one-off renders read the canonical wording)."""
    if not key:
        return 0
    h = hashlib.blake2b(f"{salt}|{(key or '').strip().lower()}".encode(), digest_size=4)
    return int.from_bytes(h.digest(), "big") % n


def variant_for(email: str | None) -> str:
    """One of `ACTIVE`, stable per prospect (their email address); the first with none."""
    return ACTIVE[_pick(email, "cta", len(ACTIVE))]


def scope(niche_plural: str | None, place: str | None) -> str:
    """What the weekly leads would be: "only construction companies in florida",
    "in florida", or "" with neither."""
    if niche_plural and place:
        return f"only {niche_plural} in {place}"
    if niche_plural:
        return f"only {niche_plural}"
    return f"in {place}" if place else ""


def cta(variant: str, where: str) -> str:
    """Email 1's last line. `where` is `scope(...)`. 2026-11-06: says what
    happens after the two weeks ("then you decide"), so free does not read as
    a trial that turns into a bill."""
    if variant == "B":
        return ("i can send 3 like these every monday, free for 2 weeks, then you decide. "
                "what kind of client should they be?")
    tail = f", {where}" if where else ""
    return (f'want 3 like these every monday{tail}? free for 2 weeks, then you decide. '
            'just reply "yes".')


# The engineer line (house rule: kept), in equivalent wordings. Shortened
# 2026-11-06 (emails ran a median 82 words).
_ENGINEER = (
    "i'm an engineer. my system finds {things} that need {help} help.",
    "i'm an engineer, and my system spots {things} that need {help} help.",
    "i'm an engineer. i built a system to find {things} that need {help} help.",
)


def engineer_line(key: str | None, things: str, help_word: str) -> str:
    return _ENGINEER[_pick(key, "engineer", len(_ENGINEER))].format(things=things, help=help_word)


def followup_question(key: str | None, state: str | None, *, cfo: bool) -> str:
    """Email 2's ask: a different, easy question from email 1's. `state` only
    when email 1's leads were in it (asking "keep these to north carolina?"
    after new york leads read as not having looked)."""
    options = []
    if state:
        options.append(f"should i keep these to {state}, or go wider?")
    if cfo:
        options.append("what's the smallest client you'd take?")
    options.append("are these the kind of clients you want, or should i look for others?")
    return options[_pick(key, "followup", len(options))]


def final_note(key: str | None) -> str:
    """Email 3: ask who should get these, or a short goodbye. 2026-11-06: no
    firm name (Apollo's "Sentinel Finance Group | Fractional CFO and
    Controller Services" printed whole), and not "if new clients ever
    matter", which read as a jab."""
    options = (
        "last one from me. if this isn't your area, who should i send these to?",
        'last one from me. if you ever want these, reply "yes" and i\'ll start '
        "sending them. if not, i won't email again.",
    )
    return options[_pick(key, "final", len(options))]
