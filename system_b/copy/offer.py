"""The offer, the ask and the closing lines (2026-11-05, the user).

The old ask ("worth a look? happy to set it up for you either way :)") named
no offer: "set it up" read as software to install, and the reader could not
tell what saying yes meant. Now every email states ONE offer, free weekly
leads in their niche for two weeks, then they decide, and asks for one small
reply. No price: that is for a call.

Two calls to action are tested against each other (`CTA_VARIANTS`): A asks
for a one-word yes; B asks what kind of client the leads should be. Each
prospect gets one, stable per email address (`variant_for`), and the batch CSV
carries it (`variant`) so the user can run each as its own Smartlead campaign
and compare replies at about 1,000 sends each.

The other fixed sentences (the engineer line, email 2's question, email 3)
come in a few equivalent wordings picked by the same hash, so 200 emails a day
do not share six identical sentences (spam filters read sameness).
"""

from __future__ import annotations

import hashlib

CTA_VARIANTS = ("A", "B")


def _pick(key: str | None, salt: str, n: int) -> int:
    """A stable choice among `n` wordings for this prospect; the first with no
    key (tests and one-off renders read the canonical wording)."""
    if not key:
        return 0
    h = hashlib.blake2b(f"{salt}|{(key or '').strip().lower()}".encode(), digest_size=4)
    return int.from_bytes(h.digest(), "big") % n


def variant_for(email: str | None) -> str:
    """"A" or "B", stable per prospect (their email address); "A" with none."""
    return CTA_VARIANTS[_pick(email, "cta", len(CTA_VARIANTS))]


def scope(niche_plural: str | None, place: str | None) -> str:
    """What the weekly leads would be: "only construction companies in florida",
    "in florida", or "" with neither."""
    if niche_plural and place:
        return f"only {niche_plural} in {place}"
    if niche_plural:
        return f"only {niche_plural}"
    return f"in {place}" if place else ""


def cta(variant: str, where: str) -> str:
    """Email 1's last line. `where` is `scope(...)`."""
    if variant == "B":
        return ("i can send 3 like these every monday, free for 2 weeks. "
                "what kind of client should they be?")
    tail = f", {where}" if where else ""
    return f'want 3 like these every monday{tail}? free for 2 weeks. just reply "yes".'


# The engineer line (house rule: kept), in equivalent wordings.
_ENGINEER = (
    "i'm an engineer. i built a system that finds {things} showing signs they need {help} help.",
    "i'm an engineer, and i built a system that spots {things} that need {help} help.",
    "i'm an engineer. my system finds {things} with a fresh reason to need {help} help.",
)


def engineer_line(key: str | None, things: str, help_word: str) -> str:
    return _ENGINEER[_pick(key, "engineer", len(_ENGINEER))].format(things=things, help=help_word)


def followup_question(key: str | None, state: str | None, *, cfo: bool) -> str:
    """Email 2's ask: a different, easy question from email 1's."""
    options = []
    if state:
        options.append(f"should i keep these to {state}, or go wider?")
    if cfo:
        options.append("what's the smallest client you'd take?")
    options.append("are these the kind of clients you want, or should i look for others?")
    return options[_pick(key, "followup", len(options))]


def final_note(key: str | None, firm: str | None) -> str:
    """Email 3: a short goodbye, or ask who handles new clients."""
    who = f"at {firm}" if firm else "there"
    options = (
        f"last one from me. if this isn't your area, who {who} handles new clients?",
        'last one from me. if new clients ever matter, reply "monday" and i\'ll start '
        "sending these. if not, i won't email again.",
    )
    return options[_pick(key, "final", len(options))]
