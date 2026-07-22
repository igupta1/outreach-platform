"""Assemble a queued item's review card and write it to the Airtable row.
This is the go-live surface: after this runs you can read the card in
Airtable and approve/edit/reject by hand.
"""

from __future__ import annotations

import json
from typing import Any

from system_b.gift.models import Gift, Prospect
from system_b.review.card import (
    build_card,
    build_followup_card,
    card_payload_email1,
    card_payload_followup,
    card_payload_linkedin,
)
from system_b.review.flags import review_flags


def format_queued_message(draft: Any) -> str:
    return f"Subject: {draft.subject}\n\n{draft.body}"


def assemble_review(
    airtable: Any,
    record_id: str,
    prospect: Prospect,
    gift: Gift,
    draft: Any,
    research: Any = None,
    *,
    stage: str = "researched",
    contact: dict[str, str] | None = None,
    niche_pack: str | None = None,
) -> dict[str, Any]:
    """Compute flags + card, write review artifacts to the row, and return the
    field payload. Leaves review_status=pending for the human.

    `niche_pack` (Track B) tags the row with its pack so follow-ups and the
    scheduler pick the right campaign; the queued draft's lead ids are stashed in
    `pending_lead_ids` so the sender can record them as sent on push."""
    flags = review_flags(prospect, gift, research, draft)
    card = build_card(prospect, gift, draft, research, flags, contact=contact)
    # The FINAL claim reflects the tiering decision (Change 2), which can differ
    # from what research first wrote (Gate B may drop a niche to generalist), so
    # write classification / match_param / niche_exclusivity here too.
    match_param = ""
    if prospect.classification == "niched" and prospect.match_param:
        kind, val = prospect.match_param
        match_param = f"{kind}={val}"
    payload = card_payload_email1(prospect, gift, draft, research, flags, contact=contact)
    fields: dict[str, Any] = {
        "review_card": card,
        "card_json": json.dumps(payload),
        "queued_message": format_queued_message(draft),
        "flags": "\n".join(flags),
        "classification": prospect.classification,
        "match_param": match_param,
        "niche_exclusivity": prospect.niche_exclusivity,
        "left_field_variant": getattr(draft, "left_field_variant", ""),
        "all_niche": gift.all_niche,
        "geo_level": gift.geo_level,
        "review_status": "pending",
        "stage": stage,
        "current_step": "1",
        "pending_lead_ids": "\n".join(l.id for l in gift.leads),
        # F2: remember the email-#1 best lead company IF it's a fractional-CFO
        # posting — the LinkedIn DM #1 add-on names it ("X is even hiring a ...").
        "li_best_cfo": gift.best_lead.company if gift.best_lead.signal_type == "job_fractional_cfo" else "",
    }
    if prospect.first_name:
        fields["first_name"] = prospect.first_name
    if niche_pack:
        fields["niche_pack"] = niche_pack
    # NB: sent_lead_ids (exclude_ids) is owned by the sender / follow-up pulls;
    # never write it here or a re-review would clobber prior sends.
    airtable.update(record_id, fields)
    return fields


def assemble_followup_review(
    airtable: Any,
    record_id: str,
    prospect: Prospect,
    lead: Any,
    draft: Any,
    *,
    step: int,
    history: list[str] | None = None,
    contact: dict[str, str] | None = None,
) -> dict[str, Any]:
    """B8 — write a follow-up (Email #2/#3) draft to the row for review. `lead`
    is the one new gift lead (or None for a fallback bump). Stage is unchanged
    (it advances only on approve+send); review_status returns to pending."""
    card = build_followup_card(
        prospect, lead, draft, draft.flags, step=step, history=history, contact=contact
    )
    payload = card_payload_followup(
        prospect, lead, draft, draft.flags, step=step, history=history, contact=contact
    )
    fields: dict[str, Any] = {
        "review_card": card,
        "card_json": json.dumps(payload),
        "queued_message": format_queued_message(draft),
        "flags": "\n".join(draft.flags),
        "review_status": "pending",
        "current_step": str(step),
        "pending_lead_ids": lead.id if lead is not None else "",
    }
    airtable.update(record_id, fields)
    return fields


def assemble_linkedin_review(
    airtable: Any,
    record_id: str,
    prospect: Prospect,
    message: str,
    *,
    step: str,
    history: list[str] | None = None,
    contact: dict[str, str] | None = None,
) -> dict[str, Any]:
    """F2 — write a LinkedIn DM draft to the row's LinkedIn track (li_* fields),
    kept separate from the email card so both channels can be pending at once."""
    payload = card_payload_linkedin(
        prospect, message, step=step, history=history, contact=contact
    )
    fields: dict[str, Any] = {
        "li_card_json": json.dumps(payload),
        "li_message": message,
        "li_step": step,
        "li_review_status": "pending",
    }
    airtable.update(record_id, fields)
    return fields
