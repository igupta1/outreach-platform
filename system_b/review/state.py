"""Step 10 review state machine. review_status drives stage transitions:
approve advances the stage, reject closes to do_not_contact, edit stores the
fixed queued_message and waits for a later approve.

Non-negotiable (build plan): only review_status == 'approved' is ever
eligible to send (enforced in M6). This module just moves the flags.
"""

from __future__ import annotations

from typing import Any

# On approval, a first-touch item moves from researched to queued-to-send.
# (Follow-up review transitions arrive with M8.)
APPROVE_ADVANCE: dict[str, str] = {
    "researched": "email_1_queued",
}

DECISIONS = ("approve", "edit", "reject")


def apply_decision(
    airtable: Any,
    record_id: str,
    decision: str,
    *,
    current_stage: str = "researched",
    edited_message: str | None = None,
) -> None:
    """Apply a reviewer decision to the row.

    approve -> review_status=approved (+ optional queued_message fix), stage
              advanced per APPROVE_ADVANCE.
    edit    -> review_status=edited, queued_message replaced; stage unchanged
              (re-review, then approve).
    reject  -> review_status=rejected, stage -> do_not_contact.
    """
    if decision == "edit":
        fields: dict[str, Any] = {"review_status": "edited"}
        if edited_message is not None:
            fields["queued_message"] = edited_message
        airtable.update(record_id, fields)
        return

    if decision == "reject":
        airtable.update(record_id, {"review_status": "rejected"})
        airtable.set_stage(record_id, "do_not_contact")
        return

    if decision == "approve":
        fields = {"review_status": "approved"}
        if edited_message is not None:
            fields["queued_message"] = edited_message
        airtable.update(record_id, fields)
        nxt = APPROVE_ADVANCE.get(current_stage)
        if nxt:
            airtable.set_stage(record_id, nxt)
        return

    raise ValueError(f"unknown decision {decision!r} (expected one of {DECISIONS})")
