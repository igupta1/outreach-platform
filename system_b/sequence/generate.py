"""Draft generation — the pure core.

Every niche runs the SAME pipeline: research the prospect's site → classify the
served vertical (verbatim, Gate A) → `resolve_gift` (Gate B) or a generalist geo
gift → code-templated per-lead lines → the FULL 3-email sequence. No state, no
Airtable — `generate_sequence` returns the sequence as a plain dict for the CSV
writer. Emails #2/#3 each gift one more fresh lead (excluding leads already used)
and carry NO recency date (Option A): they send days later, so a baked-in
"about a week ago" would drift by send time.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from system_b.clients.inventory import MAGNET_INDUSTRY
from system_b.copy.email import build_email_1, build_followup_email
from system_b.copy.linkedin import build_dm_1, build_dm_1_evergreen, build_dm_2
from system_b.gift.engine import build_gift, strongest_first
from system_b.gift.tiering import resolve_gift
from system_b.niches.base import pack_for
from system_b.research.service import research_prospect
from system_b.review.payload import build_review


def _followup_drafts(prospect: Any, gift: Any, sc: Any, pack: Any, today: date):
    """Build Email #2 and #3 up front. Returns (drafts, extra_ids, leads) where
    `leads` is aligned to steps 2 and 3 — the review gate surfaces those leads'
    evidence too.

    ONLY Email #2 gifts a lead (one fresh one, not already used across the
    sequence; Option A, so no recency date). Email #3 is the pivot: it drops the
    gift and asks what their bottleneck actually is, so no lead is pulled or
    consumed for it and its slot in `leads` is always None."""
    used = [lead.id for lead in gift.leads]
    extra_ids: list[str] = []

    prospect.sent_lead_ids = list(used)
    # Keep the sequence on-theme: email 2's lead is the same KIND as email 1's
    # (a charity audit after charity audits), from the same niche when they
    # have one, looking further out before giving up on the kind. Before
    # 2026-10-25 a geo-matched firm's email 2 took any local lead, so Houston
    # nonprofits were followed by a contractor working in Arizona.
    # (build_gift excludes already-used leads via sent_lead_ids.)
    kinds = frozenset(ld.signal_type for ld in gift.leads if ld.signal_type)
    niched = prospect.classification == "niched"
    attempts = []
    if niched:
        attempts += [dict(niche_only=True, signal_types=kinds), dict(niche_only=True)]
    attempts += [dict(signal_types=kinds, nationwide=True), {}]   # last: any lead nearby
    g = None
    for opts in attempts:
        g = build_gift(prospect, sc, target=1, pack=pack, **opts)
        if g is not None and (g.all_niche or not opts.get("niche_only")):
            break
        g = None
    lead = g.leads[0] if g else None
    if lead is not None:
        extra_ids.append(lead.id)

    drafts: list[Any] = [
        build_followup_email(lead, prospect, step=2, today=today, pack=pack,
                             include_signoff=False,
                             gift_signals={ld.signal_type for ld in gift.leads}),
        build_followup_email(None, prospect, step=3, today=today, pack=pack,
                             include_signoff=False),
    ]
    return drafts, extra_ids, [lead, None]


# --- Backlog ---------------------------------------------------------------


def _backlog_row(row: dict[str, Any], research: Any, prospect: Any,
                 reason: str | None = None) -> dict[str, Any]:
    """One held prospect, with the reason separated into three cases that mean
    very different things:

      no_magnet     They state a vertical, we mapped it, and we have no leads
                    for it. THE valuable list — it is the demand side telling
                    you which magnet to build next, firm by firm.
      no_vertical   Their site states no industry we could map. Nothing to
                    match on, so no gift is possible from any magnet. These get
                    the founder ask instead, never a gift.
      inventory_dry We DO have that magnet, but no unused lead survived the
                    match. Not a research problem — refresh or widen the
                    inventory and they qualify.
    """
    mp = getattr(prospect, "match_param", None)
    if reason is not None:
        pass                                   # caller already decided
    elif mp is None:
        reason = "no_vertical"
    elif mp[1] in MAGNET_INDUSTRY.values() or mp[0] == "niche":
        reason = "inventory_dry"
    else:
        reason = "no_magnet"
    phrases = [p for p in (getattr(research, "candidate_phrases", None) or []) if p]
    return {
        "firm_name": row.get("firm_name", ""),
        "first_name": row.get("first_name", ""),
        "email": (row.get("email") or "").strip(),
        "website": row.get("website", ""),
        "linkedin": row.get("linkedin", ""),
        "city": row.get("city", ""),
        "state": row.get("state", ""),
        "reason": reason,
        # What they say they serve, in their own words and in ours. The verbatim
        # phrase is what makes this list actionable: it is the evidence for
        # "build a construction magnet next", not an inference from a label.
        "stated_vertical": mp[1] if mp else "",
        "stated_phrase": (getattr(prospect, "niche_phrase", None)
                          or (phrases[0] if phrases else "")),
        "all_stated_phrases": " | ".join(dict.fromkeys(phrases))[:500],
    }


# The Apollo finance-firm lists, by the name `_source` gives each, and the pack
# whose voice fits a firm pulled from it.
APOLLO_LIST_PACKS = {
    "fractionalcfo": "cfo",
    "accounting": "accounting",
    "bookkeeping": "bookkeeping",
}
NEUTRAL_PACK = "finance"

# The rung a firm's NAME claims. Substrings, not words: "3CFO Solutions" and
# "AccountingRx" glue the word to something else. "cpa" alone needs word
# edges, since it hides inside other words.
_NAME_RUNGS = (
    ("cfo", re.compile(r"cfo")),
    ("bookkeeping", re.compile(r"bookkeep")),
    ("accounting", re.compile(r"accounting|accountant|accountancy|\bcpas?\b")),
)


def name_rungs(firm_name: str | None) -> set[str]:
    """Every rung the firm's own name claims: {"cfo"} for "Allegro CFO",
    {"bookkeeping", "cfo"} for "Accountix | Bookkeeping + CFO Experts"."""
    low = (firm_name or "").lower()
    return {rung for rung, pat in _NAME_RUNGS if pat.search(low)}


def choose_voice(
    rung: str | None, source: str | None, *, pack_key: str = "cfo",
    force_pack: bool = False, firm_name: str | None = None,
) -> tuple[str, str]:
    """(pack key, what chose it) for one prospect.

    In order: `--force-pack` over everything ("forced"); the rung their own
    site states ("site"); the ONE Apollo list they came from ("apollo list");
    otherwise the neutral "finance firms" voice ("neutral"). Several lists
    ("FractionalCFO+Accounting") is neutral too: a firm on the CFO and the
    accounting list may be either, and calling a CPA a bookkeeper (or a
    bookkeeper a CFO) reads as not having looked. Never a skip: every
    prospect is a finance firm, only its rung can be unknown.

    The site's rung is a word count, and it loses when the firm says otherwise
    ("disagrees"): a name that claims other rungs ("3CFO Solutions" counted
    as bookkeeping, "Abrisma Accounting" as cfo), or Apollo lists that never
    include it (a firm only on the Bookkeeping list counted as accounting).
    Those get the neutral voice: "finance firms" is true of all three, and the
    wrong rung in the one line about THEM is what the 2026-10-25 review caught
    on 4 of 20 emails.
    """
    if force_pack:
        return pack_key, "forced"
    lists = {part.strip().lower() for part in (source or "").split("+") if part.strip()}
    list_rungs = {APOLLO_LIST_PACKS[x] for x in lists if x in APOLLO_LIST_PACKS}
    if rung:
        named = name_rungs(firm_name)
        if (named and rung not in named) or (list_rungs and rung not in list_rungs):
            return NEUTRAL_PACK, "disagrees"
        return rung, "site"
    if len(lists) == 1 and list_rungs:
        return next(iter(list_rungs)), "apollo list"
    return NEUTRAL_PACK, "neutral"


def generate_sequence(
    row: dict[str, Any], sc: Any, taxonomy: dict, today: date,
    *, pack_key: str = "cfo", force_pack: bool = False,
    naturalness: Any | None = None,
) -> dict[str, Any]:
    """Research + gift + the full 3-email sequence for ONE prospect.

    Pure of any store: research the site, classify the served vertical, build a
    vertical-matched gift (or a generalist geo gift fallback), then write all
    three emails. `sc` is the niche inventory scraper; the voice comes from
    `choose_voice` (site, then Apollo list, then neutral), and `pack_key` is
    used only with `force_pack`. Returns a row dict ready for the CSV, or a `no_gift`/`error`
    marker (status != "ok") when the inventory had no matching leads.

    Signoffs are omitted (`include_signoff=False`): you add your signature + the
    CAN-SPAM footer ONCE in the Smartlead sequence editor after importing the CSV.
    """
    # Research FIRST, then pick the voice. The rung a firm sells is read off
    # their own site (research/rung.py), so a mixed export no longer tells a
    # bookkeeper the tool was "built for fractional cfos". A site that says
    # nothing separating the rungs no longer holds the firm: its Apollo list
    # decides, or the neutral voice does (`choose_voice`). `--force-pack`
    # overrides both.
    research = research_prospect(row["website"], taxonomy)
    pack_key, voice_source = choose_voice(
        getattr(research, "rung", None), row.get("_source"),
        pack_key=pack_key, force_pack=force_pack, firm_name=row.get("firm_name"),
    )
    pack = pack_for(pack_key)
    prospect, gift = resolve_gift(research, row, sc, pack=pack)
    if gift is None:
        # A prospect with no gift is NOT discarded. Most of them are firms
        # serving a vertical we simply have no lead magnet for yet — the
        # single most useful list we produce for deciding what to build next,
        # and the one thing the old "skipped" line threw away. Everything
        # needed to reach them later, plus WHY they were held, is returned so
        # `run.py` can write a backlog.
        return {
            "firm": row.get("firm_name"),
            "status": "no_gift",
            "backlog": _backlog_row(row, research, prospect),
        }
    strongest_first(gift)          # the email reads its strongest lead first
    email1 = build_email_1(
        gift, prospect, today=today, pack=pack, include_signoff=False
    )
    followups, _, followup_leads = _followup_drafts(prospect, gift, sc, pack, today)
    # The LinkedIn half of the sequence, rendered now so the operator pastes
    # rather than assembles. Both DM #1 shapes ship on every row: which one is
    # correct depends on how long the connection request sat before it was
    # accepted, which is not knowable at generation time (see copy.linkedin).
    dms = {
        "li_dm_1": build_dm_1(gift, prospect, pack=pack),
        "li_dm_1_evergreen": build_dm_1_evergreen(gift, prospect, pack=pack),
        "li_dm_2": build_dm_2(),
    }
    # Advisory read of the copy that actually VARIES: the greeting, the framing
    # and the lead lines. The closing, email 3 and the DMs are authored
    # constants, and including them bought the same three objections to house
    # style on all 30 cards — noise that buries the one card with a real defect.
    sounds_off = (
        naturalness(email1.head) if naturalness is not None else []
    )

    return {
        "firm": row.get("firm_name", ""),
        "status": "ok",
        # Which voice was used and why, so the review card can show it and the
        # operator can disagree with the evidence in front of them.
        "rung_detected": getattr(research, "rung", None),
        "rung_evidence": list(getattr(research, "rung_evidence", None) or []),
        "voice_source": voice_source,
        "gift_size": gift.gift_size,
        # Every organization this sequence names, for the allocation ledger.
        "lead_identities": [ld.allocation_key for ld in [*gift.leads, *followup_leads]
                            if ld is not None and ld.allocation_key],
        # Which campaign this row belongs to, and the day email 1 goes out. Every
        # LinkedIn step is an offset from that date, so carrying it means the
        # schedule is arithmetic rather than something to remember.
        "pack": pack.key,
        "cohort_date": today.isoformat(),
        "email": (row.get("email") or "").strip(),
        "first_name": row.get("first_name") or "",
        "last_name": row.get("last_name") or "",
        "company": row.get("firm_name") or "",
        "linkedin_url": row.get("linkedin") or "",
        "subject": email1.subject,
        "email_1": email1.body,
        "email_2": followups[0].body if followups else "",
        "email_3": followups[1].body if len(followups) > 1 else "",
        **dms,
        # Full evidence + copy for the review gate (run.py dumps this to the
        # companion review JSON; the CSV writer ignores it).
        "review": build_review(
            prospect, gift, research, email1, followups, followup_leads, row, dms,
            sounds_off, voice=(pack.key, voice_source),
        ),
    }
