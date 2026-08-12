"""LinkedIn DM copy — the second channel, under the same rules as the email.

Three messages, all deterministic code. No model writes any part of a sent DM,
the vertical claim passes the same `niche_claim` gate the subject and framing
use, and every rendered string goes through `strip_em_dashes`. The engine stays
niche-blind; the buyer-specific words live on the `NichePack`.

    DM #1  — sent when they accept the connection. Opens the way Email #1 does
             (an observation about them, then what it made us do), names ONE
             gift company as proof the thing is real, then asks for the call.
    DM #2  — three days later. Drops leads entirely and asks what their actual
             bottleneck is. No slots: the same message for every prospect.

## Why DM #1 has two versions

The fresh version says a company "just posted" a role. That is true the day the
request goes out and decays from there — the same decay `config.MAX_JOB_LEAD_AGE_DAYS`
(21) exists to bound on the email side. But a connection request has no expiry:
someone can accept it six weeks later, and a stored DM would then assert a role
that closed a month ago. Nothing in the sequence would catch it, because by then
the copy is a string in a spreadsheet rather than something this code renders.

So `build_dm_1_evergreen` names no company and no role — only the vertical, which
does not go stale. Use it for any request older than ~3 weeks. It is generated
alongside the fresh one so the choice is a lookup at send time, not a rewrite.

The channels are also kept SELF-CONTAINED: no DM references the email. While the
sending mailboxes carry a different name than the LinkedIn profile, the prospect
cannot connect the two, so "did you see my email?" reads as a stranger's error.
"""

from __future__ import annotations

from typing import Any

from system_b.copy.email import is_job_posting, job_role
from system_b.copy.honesty import strip_em_dashes
from system_b.copy.lex import city_display, state_display
from system_b.copy.subject import niche_claim
from system_b.gift.models import Gift, Prospect
from system_b.niches.base import NichePack, default_pack

# DM #2 — the last touch on either channel. Deliberately slot-free: email #3
# already proved this argument needs no personalization, and a message with no
# slots is one the operator pastes rather than assembles.
DM_2 = (
    "no worries if leads aren't what you're short on. i build systems for "
    "whatever's draining your week, so if it's something else i'd be curious "
    "what it is.\n\n"
    "worth 15 min?"
)


def _greeting(prospect: Prospect) -> str:
    """`hey paul,` — lowercase like the email's, and inline because a DM that
    opens on its own line reads as a letter, not a message."""
    return f"hey {(prospect.first_name or 'there').lower()},"


def _opener(gift: Gift, prospect: Prospect) -> str:
    """`noticed you work with real estate companies` / `saw you're based in
    atlanta` / `""`.

    The same claim Email #1's framing makes, behind the same gates: the vertical
    only when `niche_claim` allows it (gift is all-niche AND the token has a
    curated label), the geography only when the gift's leads are actually there.
    Empty when neither holds, so the DM simply opens on what we built."""
    niche = niche_claim(gift, prospect)
    if niche:
        return f"noticed you work with {niche} companies"
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if gift.geo_level == "city" and city:
        return f"saw you're based in {city}"
    if gift.geo_level == "state" and (city or state):
        return f"saw you're based in {city or state}"
    return ""


def _vertical(gift: Gift, prospect: Prospect) -> str:
    """The word the evergreen DM uses for the companies it flags: the claimed
    vertical, else the prospect's geography, else nothing (so the sentence
    degrades to a plain "companies posting finance roles")."""
    niche = niche_claim(gift, prospect)
    if niche:
        return niche
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if gift.geo_level == "city" and city:
        return city
    if gift.geo_level == "state" and (city or state):
        return city or state
    return ""


def _sign_off(pack: NichePack) -> str:
    """The second paragraph, identical in both DM #1 versions: who it was built
    for, that it is unfinished (which turns a sales ask into a research ask),
    the 15-minute ask, and the gift offered unconditionally. Compressed from
    Email #1's left-field + CTA — a DM that runs four paragraphs is not read."""
    return (
        f"built this one for {pack.dm_audience}. still tuning it, would 15 min "
        "work to hear what would make it useful for you? happy to run it for "
        "you either way :)"
    )


def _lead_clause(lead: Any, pack: NichePack) -> str:
    """`Twin Oaks Real Estate in benicia, hiring a head of finance` — the proof.

    Returns "" when the lead cannot carry the claim: a non-job signal (a breach
    describes an event, not an open role, so "just posted" would be false) or a
    title that yields no usable role. The caller falls back to the evergreen
    shape rather than printing a half-sentence."""
    if not is_job_posting(lead):
        return ""
    role = job_role(lead)
    if not role:
        return ""
    where = city_display(lead.city) or state_display(lead.state)
    who = f"{lead.company} in {where}" if where else lead.company
    return f"{who}, hiring {role}"


def build_dm_1(gift: Gift, prospect: Prospect, *, pack: NichePack | None = None) -> str:
    """DM #1, fresh: names one gift company as proof. Falls back to the evergreen
    text whenever the best lead cannot back the claim (see `_lead_clause`), so a
    caller never has to test which shape it got."""
    pack = pack or default_pack()
    clause = _lead_clause(gift.best_lead, pack)
    if not clause:
        return build_dm_1_evergreen(gift, prospect, pack=pack)
    opener = _opener(gift, prospect)
    lead_in = (
        f"{opener}, so i pulled one that just posted {pack.dm_role_singular}, "
        if opener else
        f"i pulled one that just posted {pack.dm_role_singular}, "
    )
    return strip_em_dashes(
        f"{_greeting(prospect)} {lead_in}{clause}.\n\n{_sign_off(pack)}"
    )


def build_dm_1_evergreen(
    gift: Gift, prospect: Prospect, *, pack: NichePack | None = None
) -> str:
    """DM #1 for a connection accepted long after it was sent. Names no company
    and no role, so nothing in it can age into a false claim — see the module
    docstring. Use past ~3 weeks."""
    pack = pack or default_pack()
    vertical = _vertical(gift, prospect)
    opener = _opener(gift, prospect)
    what = f"{vertical} companies" if vertical else "companies"
    built = (
        f"i built something that flags {what} posting {pack.dm_role_plural}, so "
        "i can send you a few whenever."
    )
    lead_in = f"{opener}. {built}" if opener else built
    return strip_em_dashes(
        f"{_greeting(prospect)} {lead_in}\n\n{_sign_off(pack)}"
    )


def build_dm_2() -> str:
    """DM #2 — constant, so it is the same paste for every prospect."""
    return strip_em_dashes(DM_2)
