"""Review — Step 10 card + CRM state machine (the go-live milestone).

assemble_review writes the card + queued_message + flags to the row;
apply_decision moves review_status/stage. Only an approved item may send.
"""

from system_b.review.card import build_card, build_followup_card
from system_b.review.flags import review_flags
from system_b.review.service import (
    assemble_followup_review,
    assemble_linkedin_review,
    assemble_review,
    format_queued_message,
)
from system_b.review.state import (
    APPROVE_ADVANCE,
    DECISIONS,
    apply_decision,
    is_terminal,
    mark_do_not_contact,
    mark_replied,
    mark_stage,
    stage_after_send,
)

__all__ = [
    "build_card",
    "build_followup_card",
    "review_flags",
    "assemble_review",
    "assemble_followup_review",
    "assemble_linkedin_review",
    "format_queued_message",
    "apply_decision",
    "APPROVE_ADVANCE",
    "DECISIONS",
    "stage_after_send",
    "is_terminal",
    "mark_replied",
    "mark_do_not_contact",
    "mark_stage",
]
