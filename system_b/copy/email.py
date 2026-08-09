"""Step 5 — Email #1. EVERY part is deterministic code, including each
per-lead line (hiring, breach, funding are all templated). No model writes
any part of a sent email.

5a framing table, 5b left-field rotation, 5c CTA table, 5d template fill,
5e honesty enforcement (dates, dollar amounts, flags).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from datetime import date

from system_b.copy.honesty import date_suffix, is_raise, strip_dollar_amounts, strip_em_dashes
from system_b.copy.lex import city_display, fix_articles, niche_display, state_display
from system_b.copy.subject import build_subject, niche_claim
from system_b.gift.engine import compute_match_level
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead
from system_b.niches.base import default_pack
from system_b.niches.text import noun

# Retired 2026-08-04: this fired on 21 of 23 prospects, so it drowned the flags
# that actually needed a decision. `config.MAX_JOB_LEAD_AGE_DAYS` now bounds
# posting staleness in code instead. Kept as a named constant only so a pack
# that wants an explicit "check this one" flag has a template to copy.
CFO_PRIORITY_FLAG = (
    "job_fractional_cfo / low-confidence lead present — google the posting and "
    "confirm it's still live before sending (no date in copy)"
)

# 5b — the left-field line. Rotation machinery is kept (a pack may supply
# several), but the CFO pack ships ONE authored line, so every CFO email uses it.
#
# Three jobs in 24 words, which is why the wording is load-bearing:
#   "i'm an engineer"        — credibility, with no title and no invitation to
#                              ask whether this is a side project.
#   "built this one"         — "this one" implies others exist, so the reader
#                              infers a builder without the copy claiming range.
#   "for fractional cfos"    — the TOOL is purpose-built for their profession.
#                              This is what stops the reveal of a system from
#                              reading as spray-and-pray: a machine made it, but
#                              it was made for people like them.
#   "hearing the same thing  — their peers said it, so the pain is theirs, not
#    over and over"            a guess.
#   "and nothing replaced    — the emotional beat. Naming the pain without it
#    them"                     states a fact; with it, it lands. Do not cut.
#
# House style: all lowercase, no em dashes — kept EXACTLY as authored.
LEFT_FIELD: list[str] = [
    # A
    "i'm an engineer. built this one for fractional cfos after hearing the same "
    "thing over and over, referrals dried up and nothing replaced them.",
]
LEFT_FIELD_LABELS: list[str] = ["A"]


@dataclass
class EmailDraft:
    subject: str
    body: str
    flags: list[str] = field(default_factory=list)
    left_field_variant: str = ""             # which 5b line (A-E) — logged for A/B


def rotation_for(prospect: Prospect) -> int:
    """Stable 0..(N-1) index for the left-field line (5b)."""
    return zlib.crc32(prospect.firm_name.encode("utf-8")) % len(LEFT_FIELD)


def _client_names_phrase(prospect: Prospect) -> str:
    """"A and B" from the prospect's nameable clients, or "" when there are
    none to stand behind.

    TWO names, not one and not five: one reads as a lucky grep, five reads as a
    scrape. Two is the smallest number that shows someone actually read the
    page. Names keep their own casing (they are proper nouns) inside otherwise
    lowercase prose, exactly as the gift's company names do."""
    names = [n.strip() for n in (prospect.client_names or []) if n and n.strip()]
    if len(names) < 2:
        return ""
    return f"{names[0]} and {names[1]}"


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
    companies = noun(n, "company", "companies")
    if niche:
        if prospect.niche_source == "client_list":
            # Naming the clients is what makes a 2-client threshold honest. The
            # unnamed version ("a bunch of nonprofit companies") is an inference
            # about their BUSINESS from two data points; naming them makes it a
            # citation of two facts verbatim on their own page. `client_names`
            # is already filtered to client-indicating pages upstream, and is
            # empty when we can't stand behind it — in which case we fall back
            # to the soft, unnamed phrasing.
            named = _client_names_phrase(prospect)
            if named:
                return (
                    f"noticed you've worked with {niche} companies like {named}, "
                    f"so i pulled {n} more showing they need finance help:"
                )
            return (
                f"noticed you've worked with {niche} companies, so i "
                f"pulled {n} more showing they need finance help:"
            )
        if prospect.niche_exclusivity == "one_of_several":
            # one of SEVERAL stated industries — name ONLY the one we're gifting.
            return (
                f"noticed you work with {niche} companies, so i pulled {n} more "
                f"showing they need finance help:"
            )
        # sole — a single stated focus; still soft language ("work with").
        return (
            f"saw on your site you work with {niche}, so i pulled {n} {niche} "
            f"{companies} showing they need finance help:"
        )
    # geo (all_niche FALSE): open with where they're based ONLY when the leads
    # are actually in their city or state. A geo-none gift's leads are
    # scattered, so it makes no location claim — "saw you're based in [city],
    # so i pulled..." would falsely imply the leads relate to that city.
    based = city or state
    if gift.geo_level == "city" and city:
        return (
            f"saw you're based in {city}, so i pulled {n} {companies} in {city} "
            f"showing they need finance help:"
        )
    if gift.geo_level == "state" and based:
        return (
            f"saw you're based in {based}, so i pulled {n} {state} {companies} "
            f"showing they need finance help:"
        )
    return f"i pulled {n} {companies} showing they need finance help:"


def framing_line(gift: Gift, prospect: Prospect, *, need: str) -> str:
    """Vertical-aware opener with a geo fallback — the shared framing body for the
    non-CFO packs (accounting, msp, mssp, cloud). Mirrors the CFO `_framing`
    structure exactly: it claims a customer vertical ONLY when the gift is
    all-niche (`niche_claim`, which is gated on `prospect.classification=="niched"`
    upstream), otherwise opens on geography, otherwise makes no location claim.

    `need` is the pack's value-prop clause, appended after the companies noun —
    e.g. "that just posted an it support role" or "showing they need bookkeeping
    help right now". Verb stays soft ("work with"), never "focus on"."""
    n = gift.gift_size
    niche = niche_claim(gift, prospect)
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    companies = noun(n, "company", "companies")
    if niche:
        if prospect.niche_source == "client_list":
            return (
                f"noticed you've worked with a bunch of {niche} companies, so i "
                f"pulled {n} more {need}:"
            )
        if prospect.niche_exclusivity == "one_of_several":
            return f"noticed you work with {niche} companies, so i pulled {n} more {need}:"
        return f"saw on your site you work with {niche}, so i pulled {n} {niche} {companies} {need}:"
    based = city or state
    if gift.geo_level == "city" and city:
        return f"saw you're based in {city}, so i pulled {n} {companies} in {city} {need}:"
    if gift.geo_level == "state" and based:
        return f"saw you're based in {based}, so i pulled {n} {state} {companies} {need}:"
    return f"i pulled {n} {companies} {need}:"


# The ask. One goal per email: book 15 minutes.
#
# The previous CTA ("want me to keep an eye out for atlanta ones?") optimized
# for the WRONG yes — it recruited subscribers to a free lead feed, which is
# the one business this tool is not trying to be in, and it never converted to
# a conversation. Every part of this one is deliberate:
#
#   "still tuning it"       — true, and it turns a sales ask into a research
#                             ask. People delete the first and answer the
#                             second. It also covers a weak lead honestly.
#   "would 15 min work"     — a bounded, specific, easily-declined request.
#   "what would make it     — the call's stated purpose is THEIR expertise, not
#    useful for you"          a pitch, and it opens onto everything else they
#                             need once you are actually talking.
#   "either way"            — they get the thing whether or not they take the
#                             call. Removes the transaction; this is the most
#                             persuasive clause in the email precisely because
#                             it asks for nothing.
#
# Niche/geo-agnostic on purpose: the opener and the leads already carried the
# personalization, and repeating it here made the close about the feed again.
_CTA_LINE = (
    "still tuning it. would 15 min work to hear what would make it useful for "
    "you? happy to set it up to run for you either way :)"
)


def _cta(gift: Gift, prospect: Prospect) -> str:
    return _CTA_LINE


def _funding_phrase(lead: Lead) -> str:
    """Canonical, code-templated raise description (#10): consistent across the
    batch, never a dollar amount. A Form C filing is crowdfunding (Reg CF); a
    Form D is a filed private raise. Shared by every pack whose `raise_signals`
    cover the SEC funding types (cfo, accounting, cloud)."""
    if lead.signal_type == "funding_form_c":
        return "just raised via crowdfunding"
    raw = " ".join((s.plain_words_description or "") for s in lead.signals).lower()
    if any(k in raw for k in ("reg cf", "regulation crowdfunding", "form c", "crowdfund")):
        return "just raised via crowdfunding"
    return "just filed to raise"


def _has_funding_signal(lead: Lead, raise_signals) -> bool:
    """True if the lead carries a funding signal ANYWHERE (not just as its
    primary signal_type). A hire-primary lead that also raised is a "double" —
    the highest-intent gift."""
    return any(s.type in raise_signals for s in lead.signals)


def is_job_posting(lead: Lead) -> bool:
    """A hiring signal — the company POSTED a role, so the seat is OPEN (that's
    the buying signal). Every leadgen job signal type is `job_*`."""
    return (lead.signal_type or "").startswith("job_")


def job_phrase(lead: Lead) -> str:
    """Deterministic hiring line for a job-posting lead: `is looking for a
    {role}`. `{role}` is the posting's title from the lead's evidence, stripped
    of any `| location | salary` metadata (noise in copy; it stays in the review
    evidence). NEVER says "hired" — the role is open, which is the whole point.
    Templated (not LLM) for the same reason funding is: honesty lives in code."""
    raw = next((s.plain_words_description for s in lead.signals if s.plain_words_description), "") or ""
    role = raw.split("|", 1)[0].strip().lower()
    role, _ = strip_dollar_amounts(role)          # a salary in the title never reaches copy
    role = role.strip()
    if not role:
        return "is hiring"
    return fix_articles(f"is looking for a {role}")


def is_breach(lead: Lead) -> bool:
    return (lead.signal_type or "") == "breach_disclosed"


def breach_phrase(lead: Lead) -> str:
    """Deterministic line for a breach lead: `disclosed a security incident`.

    Templated for the same reason hiring and funding are: the disclosure is a
    matter of public record, and code cannot embellish it. Deliberately SOFT
    and specific-free — the MSSP pack's own operator flag says to keep it that
    way, and the underlying record ("... reported a data breach (07/24/2026,
    California AG)") carries details this line must not repeat."""
    return "disclosed a security incident"


def _grounded_line(lead: Lead) -> str:
    """Fallback for a signal type with no template of its own: the lead's own
    verbatim evidence, never a model's paraphrase. Reached only if a new signal
    type is added without a phrase — an honest degradation, not a normal path."""
    return next(
        (s.plain_words_description for s in lead.signals if s.plain_words_description),
        "",
    )


def _lead_line(
    lead: Lead, today: date, geo_level: str, *, pack,
    with_date: bool = True,
) -> tuple[str, list[str]]:
    flags: list[str] = []

    if pack.funding_phrase is not None and is_raise(lead, pack.raise_signals):
        text = pack.funding_phrase(lead)                 # #10: ALL raises templated
    elif is_breach(lead):
        text = breach_phrase(lead)
    else:
        if is_job_posting(lead):
            # Templated hiring line — never the raw "title | location | salary"
            # evidence (goofy in copy).
            text = job_phrase(lead)
        else:
            text = _grounded_line(lead).strip().lower()
            text, stripped = strip_dollar_amounts(text)  # safety net on any $ figure
            text = fix_articles(text)                    # #11: a/an correction
            if stripped:
                flags.append(
                    f"stripped a dollar amount from {lead.company}'s line — never state a figure"
                )
        # Multi-signal ("double"): a hire-primary lead that ALSO raised — mention
        # both. The raise stays code-templated (honest, never a dollar amount).
        if pack.funding_phrase is not None and _has_funding_signal(lead, pack.raise_signals):
            raise_txt = pack.funding_phrase(lead)
            text = f"{text} and {raise_txt}" if text else raise_txt

    if with_date:                              # follow-ups pass False (Option A):
        suffix = date_suffix(lead, today)      # they send days later, so a baked-in
        if suffix:                             # relative date would drift by send time.
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
    *,
    today: date,
    rotation: int | None = None,
    pack=None,
    include_signoff: bool = True,
) -> EmailDraft:
    """Render Email #1. EVERY lead line is code-templated (hiring, breach,
    funding) — no model writes any part of a sent email. The scaffolding is
    niche-blind; `pack` (default CFO) supplies subject/framing/left-field/CTA
    voice and the raise/priority-signal knobs.

    `include_signoff=False` (the platform send path, B4a) omits the trailing
    'best, ishaan' so Smartlead's per-mailbox signature owns the signoff."""
    pack = pack or default_pack()
    flags: list[str] = []
    subject = build_subject(gift, prospect, pack=pack)
    framing = pack.framing(gift, prospect)

    lines: list[str] = []
    numbered = gift.gift_size >= 2                     # 5d: 1 lead folds in, no numbers
    for i, lead in enumerate(gift.leads):
        line, lf = _lead_line(lead, today, gift.geo_level, pack=pack)
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

    # B4a: on the platform send path the signoff is owned by each Smartlead
    # mailbox's signature field ("best, mason" etc.), so the copy engine adds
    # NONE — otherwise the send gets a double signoff. include_signoff stays
    # True for the legacy Airtable-review flow (m4_walkthrough).
    parts = [greeting, framing, "\n".join(lines), left_field, cta]
    if include_signoff:
        parts.append("best,\nishaan")
    body = strip_em_dashes("\n\n".join(parts))     # house style: no em dashes anywhere
    subject = strip_em_dashes(subject)

    # 5e / Step-10 copy flag when a priority-signal lead is present.
    if (
        pack.priority_signal and pack.priority_flag
        and any(lead.signal_type == pack.priority_signal for lead in gift.leads)
    ):
        flags.append(pack.priority_flag)

    return EmailDraft(subject=subject, body=body, flags=flags, left_field_variant=variant)


def _followup_qualifier(lead: Lead, prospect: Prospect) -> str:
    """An HONEST qualifier for a follow-up lead ("dental ", "in denver ", ...),
    used only when the lead genuinely matches that facet of the prospect. Empty
    when nothing matches, so we never imply a relationship that isn't there."""
    lvl = compute_match_level(lead, prospect)
    if prospect.classification == "niched" and lvl is not None and lvl <= 3:
        niche = niche_display(prospect.match_param)
        if niche:
            return f"{niche} "
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if city and lead.city and city_display(lead.city) == city:
        return f"in {city} "
    if state and lead.state and state_display(lead.state) == state:
        return f"in {state} "
    return ""


def build_followup_email(
    lead: Lead | None,
    prospect: Prospect,
    *,
    step: int,
    today: date,
    pack=None,
    include_signoff: bool = False,
    segment_note: str = "",
) -> EmailDraft:
    """Email #2 / #3 (B3, B4). Threaded under Email #1, so the SUBJECT IS BLANK
    (Smartlead sends a blank-subject step as a reply on the same thread).

    Two shapes:
      * value    — a genuinely NEW lead surfaced (`lead` given): one honest lead
                   line + a soft continue-CTA.
      * fallback — no new lead (`lead is None`): a light bump, no fabricated lead.

    Honesty is identical to Email #1: dates only for high-confidence signals,
    raises templated with no dollar figure, all via `_lead_line`. Signoff is
    owned by the Smartlead mailbox signature (B4a) → default include_signoff=False."""
    if step not in (2, 3):
        raise ValueError(f"follow-up step must be 2 or 3, got {step!r}")
    pack = pack or default_pack()
    flags: list[str] = []
    final = step == 3

    if lead is not None:
        line, lf = _lead_line(lead, today, "none", pack=pack, with_date=False)
        flags.extend(lf)
        qual = _followup_qualifier(lead, prospect)
        opener = "last one from me." if final else f"found one more {qual}showing the same signal:"
        # The tails ask for the same thing email #1 did. The old ones ("want me
        # to keep sending these?") recruited a subscriber, which is the wrong
        # yes: a sequence whose steps chase different outcomes converts on the
        # easiest one, and that was never the call.
        tail = (
            "if this isn't useful no worries at all, i'll stop here. if it is, "
            "i'd still love 15 min to tune it for you."
            if final else
            "offer still stands on setting it up for you, 15 min whenever works."
        )
        # Segment context (step 2 only): a DIFFERENT kind of value from "here is
        # one more lead", which is what stops the follow-up reading as a bump.
        # Empty whenever the segment is too thin to say anything (see
        # copy.segment), so a sparse state degrades to the plain shape.
        body_parts = [opener, line]
        if segment_note and not final:
            body_parts.append(segment_note)
        body_parts.append(tail)
        core = "\n\n".join(body_parts)
        if pack.priority_signal and lead.signal_type == pack.priority_signal and pack.priority_flag:
            flags.append(pack.priority_flag)
    else:
        niche = niche_claim_or_geo(prospect)
        sig = pack.followup_signal
        if final:
            core = (
                f"last nudge from me, happy to keep surfacing {niche} companies "
                f"the moment they show {sig}. just say the word."
            )
        else:
            core = (
                f"circling back, still keeping an eye out for {niche} companies "
                f"showing {sig}. 15 min whenever works if you want it set up."
            )

    parts = [core]
    if include_signoff:
        parts.append("best,\nishaan")
    body = strip_em_dashes("\n\n".join(parts))     # house style: no em dashes anywhere
    return EmailDraft(subject="", body=body, flags=flags, left_field_variant="")


def niche_claim_or_geo(prospect: Prospect) -> str:
    """Bare descriptor for the fallback follow-up ('dental', 'denver', or a
    neutral default) — no lead to anchor a claim, so keep it soft/geographic."""
    if prospect.classification == "niched":
        niche = niche_display(prospect.match_param)
        if niche:
            return niche
    return city_display(prospect.city) or state_display(prospect.state) or "these kinds of"
