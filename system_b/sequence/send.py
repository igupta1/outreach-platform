"""B1/B2 — approve a queued draft and push it to the platform.

Dispatches on the row's `current_step`:
  * step 1  -> `add_lead` (first touch) + record the Smartlead lead id.
  * step 2/3 -> `set_followup` (update the {{email_2/3}} variable on the same
    thread) — no new send is created; Smartlead's step timer sends it.

Either way it moves the just-sent gift lead(s) from `pending_lead_ids` into
`sent_lead_ids`, appends the message to the history, advances the stage, and
sets the next follow-up due date. A frozen (replied / opted-out) row never sends.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from system_b import config
from system_b.review.state import stage_after_send
from system_b.sending.base import EmailSender
from system_b.sequence.rows import (
    NotEligibleError,
    append_history,
    field,
    history_entry,
    join_id_list,
    parse_id_list,
    parse_queued_message,
    resolve_campaign,
    resolve_pack_key,
)


def _next_due(step_sent: int, today: date) -> date | None:
    """When the NEXT step becomes due after sending `step_sent`."""
    gap = config.SEQUENCE_STEP_GAP_DAYS.get(step_sent + 1)
    return today + timedelta(days=gap) if gap is not None else None


def approve_and_send(
    at: Any,
    sender: EmailSender,
    record_id: str,
    *,
    today: date | None = None,
    edited_message: str | None = None,
) -> dict[str, Any]:
    """Approve the currently-queued draft and push it. Returns a small result
    dict. Raises on a hard misconfiguration (no email / no lead id / frozen)."""
    today = today or date.today()
    rec = at.get(record_id)
    fields = rec["fields"]

    if fields.get("frozen"):
        raise RuntimeError(f"row {record_id} is frozen (replied/opted-out) — refusing to send")
    # HARD send-safety gate: a prospect can NEVER be pushed until explicitly
    # marked eligible. Enforced here in the library so no caller can bypass it.
    if not fields.get("eligible_for_send"):
        raise NotEligibleError(
            f"row {record_id} is not eligible_for_send — refusing to push. "
            "Mark the prospect eligible before approving."
        )

    step = int(field(fields, "current_step", "1") or "1")
    pack_key = resolve_pack_key(fields)
    campaign_id = resolve_campaign(fields, pack_key)
    subject, body = parse_queued_message(edited_message or fields.get("queued_message"))
    pending = parse_id_list(fields.get("pending_lead_ids"))
    already = parse_id_list(fields.get("sent_lead_ids"))
    sent_on = today.isoformat()

    updates: dict[str, Any] = {
        "review_status": "approved",
        "sent_lead_ids": join_id_list(already + pending),
        "pending_lead_ids": "",
        "message_history": append_history(
            fields.get("message_history"), history_entry(step, subject, body, sent_on)
        ),
    }
    if edited_message is not None:
        updates["queued_message"] = edited_message

    due = _next_due(step, today)
    updates["due_date"] = due.isoformat() if due else ""
    updates["next_action"] = (
        f"await reply / step {step + 1}" if due else "sequence complete — await reply"
    )

    if step == 1:
        email = field(fields, "email", "")
        if not email:
            raise RuntimeError(f"row {record_id} has no email — cannot add lead")
        lead_id = sender.add_lead(
            campaign_id,
            email=email,
            first_name=field(fields, "first_name", None) or None,
            subject=subject,
            email_1=body,
        )
        updates["smartlead_campaign_id"] = campaign_id
        updates["smartlead_lead_id"] = lead_id
        # Day-0 anchor for the unified cadence (F1) + queue the blank LinkedIn
        # connection request for the operator to send by hand.
        updates["sequence_started_at"] = sent_on
        updates["li_connect_pending"] = True
    else:
        lead_id = field(fields, "smartlead_lead_id", "")
        if not lead_id:
            raise RuntimeError(f"row {record_id} has no smartlead_lead_id — cannot set follow-up")
        email = field(fields, "email", "")
        if not email:
            raise RuntimeError(f"row {record_id} has no email — cannot update lead")
        sender.set_followup(campaign_id, lead_id, step=step, body=body, email=email)

    at.update(record_id, updates)
    at.set_stage(record_id, stage_after_send(step))
    return {"record_id": record_id, "step": step, "lead_id": lead_id, "stage": stage_after_send(step)}
