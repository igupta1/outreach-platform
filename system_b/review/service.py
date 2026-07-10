"""Assemble a queued item's review card and write it to the Airtable row.
This is the go-live surface: after this runs you can read the card in
Airtable and approve/edit/reject by hand.
"""

from __future__ import annotations

from typing import Any

from system_b.gift.models import Gift, Prospect
from system_b.review.card import build_card
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
) -> dict[str, Any]:
    """Compute flags + card, write review artifacts to the row, and return the
    field payload. Leaves review_status=pending for the human."""
    flags = review_flags(prospect, gift, research, draft)
    card = build_card(prospect, gift, draft, research, flags, contact=contact)
    fields: dict[str, Any] = {
        "review_card": card,
        "queued_message": format_queued_message(draft),
        "flags": "\n".join(flags),
        "all_niche": gift.all_niche,
        "geo_level": gift.geo_level,
        "review_status": "pending",
        "stage": stage,
    }
    # NB: sent_lead_ids (exclude_ids) is owned by the sender (M6) / follow-up
    # pulls (M8); never write it here or a re-review would clobber prior sends.
    airtable.update(record_id, fields)
    return fields
