"""The offer, the ask and the closing lines (2026-11-05, the user).

The old ask ("worth a look? happy to set it up for you either way :)") named
no offer: "set it up" read as software to install, and the reader could not
tell what saying yes meant. Now every email states ONE offer, 3 leads every
monday matched to the clients they want, and asks for one small reply. No
price: that is for a call.

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
    """Email 1's last line. 2026-11-11, the user: say plainly what the offer is
    ("what is it you offer?" came back as a reply) and do not sound salesy:
    an offer to help, no "free", "trial" or "then you decide". The scope
    (`where`) is no longer printed: "matched to the clients you want" says it
    and leaves the call to settle which. A "yes" is answered with a short call
    to get their industries and area right."""
    if variant == "B":
        return ("happy to send 3 like these every monday. "
                "what kind of client should they be?")
    return "happy to send 3 like these every monday, matched to your clients. worth a look?"


# The engineer line (house rule: kept), in equivalent wordings. 2026-11-11, the
# user ("i want to come off not salesy"): a builder who is early and asking
# whether it helps, which turns a pitch into a question. 2026-11-13: shortened
# (emails ran 97 words); the leads already say what it finds.
_ENGINEER = ("i'm an engineer. i built this and i'm seeing if it helps firms like yours.",)


def engineer_line(key: str | None, things: str = "", help_word: str = "") -> str:
    """`things` and `help_word` are kept for callers; the short wordings
    (2026-11-13) name neither."""
    return _ENGINEER[_pick(key, "engineer", len(_ENGINEER))].format(things=things, help=help_word)


def followup_question(niche: str | None, place: str | None) -> str:
    """Email 2's question, one wording per case (2026-11-13, the user: "let's
    not vary the copy"). Leads in their industry: offer another industry.
    Otherwise leads near them: keep to that place or go wider."""
    if niche:
        return f"want more {niche}, or a different industry?"
    if place:
        return f"should i keep these to {place}, or go wider?"
    return "are these the kind of clients you want, or should i look for others?"


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
