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
from system_b.copy.lex import city_display, fix_articles, state_display
from system_b.copy.subject import build_subject, niche_claim
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import default_pack

# 5e flag emitted when a priority-signal (cfo_wanted) lead is in the gift — the
# CFO pack's `priority_flag`.
CFO_PRIORITY_FLAG = (
    "cfo_wanted / low-confidence lead present — google the posting and "
    "confirm it's still live before sending (no date in copy)"
)

# 5b — five left-field lines. Rotation is deterministic per prospect so a
# redraft is stable and tests are reproducible. The chosen variant's LABEL is
# logged on the draft / review card / row so replies can be A/B'd by phrasing.
# House style: all lowercase, no em dashes — kept EXACTLY as authored.
LEFT_FIELD: list[str] = [
    # A
    "most fractional cfos i talk to say referrals were great, till they dried "
    "up. built this to catch companies the day they show a finance-need signal.",
    # B
    "every fractional cfo i talk to says the same thing, referrals carried them "
    "till they didn't. so i built a feed that catches companies the day they "
    "show a finance-need signal.",
    # C
    "most fractional cfos i know swear by referrals, right up until the well "
    "runs dry. built this to catch companies the moment a finance-need signal "
    "shows up.",
    # D
    "the fractional cfos i talk to say nothing beats a referral, till there "
    "aren't any left. so i built a feed that surfaces companies the day they "
    "signal they need finance help.",
    # E
    "most fractional cfos i talk to loved referrals, till the pipeline went "
    "quiet. built this to catch companies right when a finance-need signal "
    "shows up.",
]
LEFT_FIELD_LABELS: list[str] = ["A", "B", "C", "D", "E"]


@dataclass
class EmailDraft:
    subject: str
    body: str
    flags: list[str] = field(default_factory=list)
    left_field_variant: str = ""             # which 5b line (A-E) — logged for A/B


def rotation_for(prospect: Prospect) -> int:
    """Stable 0..(N-1) index for the left-field line (5b)."""
    return zlib.crc32(prospect.firm_name.encode("utf-8")) % len(LEFT_FIELD)


def _framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    # Framing ALWAYS uses the clean mapped niche word (niche_claim -> niche_display),
    # NEVER the raw scraped phrase — the verbatim phrase is often a nav blob
    # ("WHO WE SERVE...", "designed for:") and can leak a dollar figure. The
    # exact phrase stays in evidence / the review card, not the sent copy.
    # The VERB stays soft — "work with", never "focus on" — so we never overclaim
    # a specialty we might be wrong about. A client list reads as a sole focus.
    if niche:
        if prospect.niche_source == "client_list":
            return (
                f"noticed you've worked with a bunch of {niche} companies, so i "
                f"pulled {n} more showing they need finance help right now:"
            )
        if prospect.niche_exclusivity == "one_of_several":
            # one of SEVERAL stated industries — name ONLY the one we're gifting.
            return (
                f"noticed you work with {niche} companies, so i pulled {n} more "
                f"showing they need finance help right now:"
            )
        # sole — a single stated focus; still soft language ("work with").
        return (
            f"saw on your site you work with {niche}, so i pulled {n} {niche} "
            f"companies showing they need finance help right now:"
        )
    # geo (all_niche FALSE): open with where they're based ONLY when the leads
    # are actually in their city or state. A geo-none gift's leads are
    # scattered, so it makes no location claim — "saw you're based in [city],
    # so i pulled..." would falsely imply the leads relate to that city.
    based = city or state
    if gift.geo_level == "city" and city:
        return (
            f"saw you're based in {city}, so i pulled {n} companies in {city} "
            f"showing they need finance help right now:"
        )
    if gift.geo_level == "state" and based:
        return (
            f"saw you're based in {based}, so i pulled {n} {state} companies "
            f"showing they need finance help right now:"
        )
    return f"i pulled {n} companies showing they need finance help right now:"


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


def _funding_phrase(lead: Lead) -> str:
    """Canonical, code-templated raise description (#10): consistent across the
    batch, never a dollar amount. Crowdfunding vs a filed private raise; a
    double_signal also names the hiring half (its confluence value)."""
    raw = " ".join((s.plain_words_description or "") for s in lead.signals).lower()
    base = ("just raised via crowdfunding"
            if any(k in raw for k in ("reg cf", "regulation crowdfunding", "form c", "crowdfund"))
            else "just filed to raise")
    if lead.signal_type == "double_signal":
        base += " and is hiring finance leadership"
    return base


def _lead_line(
    lead: Lead, description: str, today: date, geo_level: str, *, pack,
) -> tuple[str, list[str]]:
    flags: list[str] = []

    if pack.funding_phrase is not None and is_raise(lead, pack.raise_signals):
        text = pack.funding_phrase(lead)                 # #10: ALL raises templated
    else:
        text = (description or "").strip().lower()
        text, stripped = strip_dollar_amounts(text)      # safety net on any LLM $ figure
        text = fix_articles(text)                        # #11: a/an correction
        if stripped:
            flags.append(
                f"stripped a dollar amount from {lead.company}'s line — never state a figure"
            )

    suffix = date_suffix(lead, today)          # '' when low-confidence / undated
    if suffix:
        text = f"{text}, {suffix}" if text else suffix

    loc = city_display(lead.city) or state_display(lead.state)
    line = f"{lead.company}, {loc}: {text}" if loc else f"{lead.company}: {text}"

    if lead.domain is None:
        flags.append(f"domainless lead ({lead.company}) — google the name to confirm it's real")
    if is_raise(lead, pack.raise_signals) and geo_level == "city":
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
    pack=None,
) -> EmailDraft:
    """Render Email #1. `descriptions` maps lead id -> the LLM's freeform
    'what they did, plain words' (no dates, no dollar amounts). The scaffolding
    is niche-blind; `pack` (default CFO) supplies subject/framing/left-field/CTA
    voice and the raise/priority-signal knobs."""
    pack = pack or default_pack()
    flags: list[str] = []
    subject = build_subject(gift, prospect, pack=pack)
    framing = pack.framing(gift, prospect)

    lines: list[str] = []
    numbered = gift.gift_size >= 2                     # 5d: 1 lead folds in, no numbers
    for i, lead in enumerate(gift.leads):
        line, lf = _lead_line(lead, descriptions.get(lead.id, ""), today, gift.geo_level, pack=pack)
        flags.extend(lf)
        lines.append(f"{i + 1}. {line}" if numbered else line)

    n_lines = len(pack.left_field)
    idx = rotation if rotation is not None else (
        zlib.crc32(prospect.firm_name.encode("utf-8")) % n_lines
    )
    left_field = pack.left_field[idx]
    variant = pack.left_field_labels[idx]
    cta = pack.cta(gift, prospect)
    # lowercase prose, proper nouns intact: "hey dora," not "hey Dora,".
    greeting = f"hey {(prospect.first_name or 'there').lower()},"

    body = "\n\n".join([greeting, framing, "\n".join(lines), left_field, cta, "best,\nishaan"])

    # 5e / Step-10 copy flag when a priority-signal lead is present.
    if (
        pack.priority_signal and pack.priority_flag
        and any(l.signal_type == pack.priority_signal for l in gift.leads)
    ):
        flags.append(pack.priority_flag)

    return EmailDraft(subject=subject, body=body, flags=flags, left_field_variant=variant)
