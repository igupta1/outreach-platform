"""Step 10 / B2 — the full sequence state machine. `review_status` drives the
reviewer decisions (approve/edit/reject); separate event transitions
(send / reply / unsubscribe / call) move the `stage` as the world changes.

Non-negotiable (build plan): only review_status == 'approved' is ever eligible
to send (enforced by the sequence layer). This module moves the flags; the
sequence layer performs the Smartlead side effects.
"""

from __future__ import annotations

from typing import Any

# The ordered stage list (mirrors AirtableClient.STAGES). Email steps first,
# then the LinkedIn steps (wired copy lands with Track F), then terminals.
STAGES: list[str] = [
    "researched", "email_1_queued", "email_1_sent", "email_2_sent",
    "email_3_sent", "connect_sent", "connect_accepted", "dm_1_sent",
    "dm_2_sent", "replied", "call_booked", "closed", "do_not_contact",
]

# review_status == approved advances the stage per the current stage. First
# touch: researched -> email_1_queued (the sequence layer then pushes to
# Smartlead and marks email_1_sent). Follow-up approvals advance the sent step.
APPROVE_ADVANCE: dict[str, str] = {
    "researched": "email_1_queued",
    "email_1_sent": "email_2_sent",
    "email_2_sent": "email_3_sent",
}

# Stage a lead reaches once a given step is actually pushed to the platform.
SENT_STAGE: dict[int, str] = {1: "email_1_sent", 2: "email_2_sent", 3: "email_3_sent"}

# Terminal stages — the scheduler never generates or sends for these.
TERMINAL: frozenset[str] = frozenset({"replied", "call_booked", "closed", "do_not_contact"})

DECISIONS = ("approve", "edit", "reject")


def stage_after_send(step: int) -> str:
    if step not in SENT_STAGE:
        raise ValueError(f"no sent-stage for step {step!r}")
    return SENT_STAGE[step]


def is_terminal(stage: str | None) -> bool:
    return stage in TERMINAL


def apply_decision(
    airtable: Any,
    record_id: str,
    decision: str,
    *,
    current_stage: str = "researched",
    edited_message: str | None = None,
) -> None:
    """Apply a reviewer decision to the row (flags only — no send).

    approve -> review_status=approved (+ optional queued_message fix), stage
              advanced per APPROVE_ADVANCE.
    edit    -> review_status=edited, queued_message replaced; stage unchanged.
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


# --- event transitions (driven by the sender + the reply webhook) ---------

def mark_replied(
    airtable: Any, record_id: str, *, reply_body: str | None = None,
    replied_at: str | None = None,
) -> None:
    """A reply arrived (B5): freeze the sequence and record the reply. `frozen`
    tells the scheduler to skip this prospect on every channel."""
    fields: dict[str, Any] = {"stage": "replied", "frozen": True}
    if reply_body is not None:
        fields["last_reply"] = reply_body
    if replied_at is not None:
        fields["replied_at"] = replied_at
    airtable.update(record_id, fields)


def mark_do_not_contact(airtable: Any, record_id: str, *, reason: str | None = None) -> None:
    """Unsubscribe / negative reply / manual opt-out (B6). Freezes and closes."""
    fields: dict[str, Any] = {"stage": "do_not_contact", "frozen": True}
    if reason:
        fields["next_action"] = reason
    airtable.update(record_id, fields)


def mark_stage(airtable: Any, record_id: str, stage: str) -> None:
    """Set a concrete stage (used by the sequence layer after a platform push)."""
    airtable.set_stage(record_id, stage)
