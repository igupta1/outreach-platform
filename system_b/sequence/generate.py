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

from datetime import date
from typing import Any

from system_b.copy.email import build_email_1, build_followup_email
from system_b.gift.engine import build_gift
from system_b.gift.tiering import resolve_gift
from system_b.niches.base import pack_for
from system_b.research.service import research_prospect
from system_b.review.payload import build_review


def _followup_drafts(prospect: Any, gift: Any, sc: Any, pack: Any, today: date):
    """Build Email #2 and #3 up front. Each pulls one fresh lead not already used
    across the sequence (Option A: no recency date). Returns
    (drafts, extra_ids, leads) where `leads` is aligned to steps 2 and 3 (each
    entry is the lead used, or None when the well ran dry) — the review gate
    surfaces those leads' evidence too."""
    used = [lead.id for lead in gift.leads]
    drafts: list[Any] = []
    extra_ids: list[str] = []
    leads: list[Any] = []
    for step in (2, 3):
        prospect.sent_lead_ids = list(used)
        # Keep a niched sequence on-theme: pull the follow-up from the SAME niche
        # as Email #1 (build_gift excludes already-used leads via sent_lead_ids),
        # falling back to a geo lead only when the niche well has run dry.
        g = None
        if prospect.classification == "niched":
            gn = build_gift(prospect, sc, target=1, niche_only=True, pack=pack)
            if gn is not None and gn.all_niche:
                g = gn
        if g is None:
            g = build_gift(prospect, sc, target=1, pack=pack)   # geo fallback
        lead = g.leads[0] if g else None
        if lead is not None:
            used.append(lead.id)
            extra_ids.append(lead.id)
        leads.append(lead)
        drafts.append(build_followup_email(
            lead, prospect, step=step, today=today, pack=pack,
            include_signoff=False,
        ))
    return drafts, extra_ids, leads


def generate_sequence(
    row: dict[str, Any], sc: Any, taxonomy: dict, today: date,
    *, pack_key: str = "cfo",
) -> dict[str, Any]:
    """Research + gift + the full 3-email sequence for ONE prospect.

    Pure of any store: research the site, classify the served vertical, build a
    vertical-matched gift (or a generalist geo gift fallback), then write all
    three emails. `sc` is the niche inventory scraper; `pack_key` selects voice +
    lead preference. Returns a row dict ready for the CSV, or a `no_gift`/`error`
    marker (status != "ok") when the inventory had no matching leads.

    Signoffs are omitted (`include_signoff=False`): you add your signature + the
    CAN-SPAM footer ONCE in the Smartlead sequence editor after importing the CSV.
    """
    pack = pack_for(pack_key)
    research = research_prospect(row["website"], taxonomy)
    prospect, gift = resolve_gift(research, row, sc, pack=pack)
    if gift is None:
        return {"firm": row.get("firm_name"), "status": "no_gift"}
    email1 = build_email_1(
        gift, prospect, today=today, pack=pack, include_signoff=False
    )
    followups, _, followup_leads = _followup_drafts(prospect, gift, sc, pack, today)
    return {
        "firm": row.get("firm_name", ""),
        "status": "ok",
        "gift_size": gift.gift_size,
        "email": (row.get("email") or "").strip(),
        "first_name": row.get("first_name") or "",
        "company": row.get("firm_name") or "",
        "subject": email1.subject,
        "email_1": email1.body,
        "email_2": followups[0].body if followups else "",
        "email_3": followups[1].body if len(followups) > 1 else "",
        # Full evidence + copy for the review gate (run.py dumps this to the
        # companion review JSON; the CSV writer ignores it).
        "review": build_review(
            prospect, gift, research, email1, followups, followup_leads, row
        ),
    }
