"""Step 5 — Email #1. Everything structural is deterministic code; the LLM
fills ONLY the freeform per-lead descriptions (passed in as `descriptions`).

5a framing table, 5b left-field rotation, 5c CTA table, 5d template fill,
5e honesty enforcement (dates, dollar amounts, flags).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from datetime import date

from system_b.copy.honesty import date_suffix, is_raise, strip_dollar_amounts
from system_b.copy.lex import city_display, state_display
from system_b.copy.subject import build_subject, niche_claim
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead

# 5b — three left-field lines. Rotation is deterministic per prospect so a
# redraft is stable and tests are reproducible.
LEFT_FIELD: list[str] = [
    "bit random, I know, but most fractional CFOs I talk to say sourcing is "
    "the part they hate. finding companies right when they need finance help, "
    "before someone else gets there. so I built a feed that catches these the "
    "day the signal shows up.",
    "totally out of the blue, but every fractional CFO I talk to says the same "
    "thing: the hard part isn't the work, it's finding companies at the exact "
    "moment they need you. that's what my feed is built to catch.",
    "cold email, fair warning. I keep hearing from fractional CFOs that "
    "sourcing is the worst part of the job, so I built a feed that catches "
    "these signals the day they show up.",
]


@dataclass
class EmailDraft:
    subject: str
    body: str
    flags: list[str] = field(default_factory=list)


def rotation_for(prospect: Prospect) -> int:
    """Stable 0..2 index for the left-field line (5b)."""
    return zlib.crc32(prospect.firm_name.encode("utf-8")) % len(LEFT_FIELD)


def _framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if niche:
        if prospect.niche_source == "client_list":
            return (
                f"noticed you've worked with a bunch of {niche} companies, so I "
                f"pulled {n} more showing they need finance help right now:"
            )
        phrase = prospect.niche_phrase or niche
        return (
            f"saw on your site you focus on {phrase}, so I pulled {n} {niche} "
            f"companies showing they need finance help right now:"
        )
    if gift.geo_level == "city":
        return (
            f"saw you're based in {city}, so I pulled {n} local companies "
            f"showing they need finance help right now:"
        )
    if gift.geo_level == "state":
        return (
            f"saw you're based in {city}, so I pulled {n} {state} companies "
            f"showing they need finance help right now:"
        )
    return f"I pulled {n} companies showing they need finance help right now:"


def _cta(gift: Gift, prospect: Prospect) -> str:
    niche = niche_claim(gift, prospect)
    if niche:
        return f"want me to keep an eye out for {niche} ones and send them your way?"
    if gift.geo_level == "city":
        return (
            f"want me to keep an eye out for {city_display(prospect.city)} ones "
            f"and send them your way?"
        )
    if gift.geo_level == "state":
        return (
            f"want me to keep an eye out for {state_display(prospect.state)} ones "
            f"and send them your way?"
        )
    return "want me to keep an eye out and send new ones your way?"


def _lead_line(lead: Lead, description: str, today: date, geo_level: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    text = (description or "").strip()

    if is_raise(lead):
        text, stripped = strip_dollar_amounts(text)
        if stripped:
            flags.append(
                f"stripped a dollar amount from {lead.company}'s line — a raise "
                "is a filing target, never state an amount"
            )

    suffix = date_suffix(lead, today)          # '' when low-confidence / undated
    if suffix:
        text = f"{text}, {suffix}" if text else suffix

    loc = city_display(lead.city) or state_display(lead.state)
    line = f"{lead.company}, {loc}: {text}" if loc else f"{lead.company}: {text}"

    if lead.domain is None:
        flags.append(f"domainless lead ({lead.company}) — google the name to confirm it's real")
    if is_raise(lead) and geo_level == "city":
        flags.append(
            f"funding lead ({lead.company}) drives a city claim — its city may be "
            "a registered address, not HQ"
        )
    return line, flags


def build_email_1(
    gift: Gift,
    prospect: Prospect,
    descriptions: dict[str, str],
    *,
    today: date,
    rotation: int | None = None,
) -> EmailDraft:
    """Render Email #1. `descriptions` maps lead id -> the LLM's freeform
    'what they did, plain words' (no dates, no dollar amounts)."""
    flags: list[str] = []
    subject = build_subject(gift, prospect)
    framing = _framing(gift, prospect)

    lines: list[str] = []
    numbered = gift.gift_size >= 2                     # 5d: 1 lead folds in, no numbers
    for i, lead in enumerate(gift.leads):
        line, lf = _lead_line(lead, descriptions.get(lead.id, ""), today, gift.geo_level)
        flags.extend(lf)
        lines.append(f"{i + 1}. {line}" if numbered else line)

    idx = rotation if rotation is not None else rotation_for(prospect)
    left_field = LEFT_FIELD[idx]
    cta = _cta(gift, prospect)
    greeting = f"hey {prospect.first_name or 'there'},"

    body = "\n\n".join([greeting, framing, "\n".join(lines), left_field, cta, "best,\nishaan"])

    # 5e / Step-10 copy flags tied to the honesty rules.
    if any(l.signal_type == "cfo_wanted" for l in gift.leads):
        flags.append(
            "cfo_wanted / low-confidence lead present — google the posting and "
            "confirm it's still live before sending (no date in copy)"
        )

    return EmailDraft(subject=subject, body=body, flags=flags)
