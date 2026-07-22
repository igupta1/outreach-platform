"""F — LinkedIn card lifecycle actions (kept off the email stage machine).

A LinkedIn card lives in the row's li_* fields, so approving/rejecting/editing
or marking it sent NEVER touches the email `stage` or Smartlead. `li_progress`
records the last LinkedIn step done, which drives what the scheduler offers next.
"""

from __future__ import annotations

import json
from typing import Any

from system_b.copy.honesty import lint_free_text
from system_b.sequence.rows import NotEligibleError


def approve_linkedin(at: Any, record_id: str) -> dict[str, Any]:
    """Approve a DM -> it moves to the LinkedIn queue (worked by hand). No send.
    Gated by the same eligible_for_send guard as email — a non-eligible prospect
    never reaches the send-queue."""
    if not at.get(record_id)["fields"].get("eligible_for_send"):
        raise NotEligibleError(
            f"row {record_id} is not eligible_for_send — refusing to queue the LinkedIn DM."
        )
    at.update(record_id, {"li_review_status": "approved"})
    return {"approved": True, "pushed": False, "channel": "linkedin", "record_id": record_id}


def reject_linkedin(at: Any, record_id: str) -> dict[str, Any]:
    """Skip this DM only — advance li_progress past it, leave the email track alone."""
    step = at.get(record_id)["fields"].get("li_step") or ""
    at.update(record_id, {
        "li_review_status": "rejected", "li_progress": step,
        "li_step": "", "li_card_json": "", "li_message": "",
    })
    return {"status": "rejected", "channel": "linkedin", "record_id": record_id}


def edit_linkedin(at: Any, record_id: str, body: str) -> dict[str, Any]:
    """Honesty-lint the edited DM (strip $ / warn on dates), store the cleaned text."""
    clean, warnings = lint_free_text(body)
    f = at.get(record_id)["fields"]
    payload = json.loads(f.get("li_card_json") or "{}")
    payload["message"] = {"subject": "", "body": clean}
    at.update(record_id, {
        "li_message": clean, "li_card_json": json.dumps(payload), "li_review_status": "edited",
    })
    return {"status": "edited", "channel": "linkedin", "record_id": record_id,
            "warnings": warnings, "cleaned_body": clean}


def mark_connect_sent(at: Any, record_id: str) -> dict[str, Any]:
    """Operator sent the Day-0 connection request by hand."""
    at.update(record_id, {"li_connect_pending": False, "li_progress": "connect"})
    return {"status": "ok", "record_id": record_id, "li_progress": "connect"}


def mark_dm_sent(at: Any, record_id: str) -> dict[str, Any]:
    """Operator sent the approved DM by hand — record progress, clear the card."""
    step = at.get(record_id)["fields"].get("li_step") or "dm_1"
    at.update(record_id, {
        # li_review_status is a singleSelect -> clear with None, never "".
        "li_progress": step, "li_review_status": None, "li_step": "",
        "li_card_json": "", "li_message": "",
    })
    return {"status": "ok", "record_id": record_id, "li_progress": step}
