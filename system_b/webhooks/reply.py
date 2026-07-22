"""B5 (SAFETY-CRITICAL) — the reply-freeze handler.

A Smartlead reply webhook keys on `to_email` (no lead_id in the payload). On a
reply we:
  1. find the prospect by email,
  2. PAUSE the Smartlead lead so no further step sends (best-effort — a pause
     failure must not stop the freeze),
  3. mark the row replied + frozen (the scheduler now skips it on every channel),
  4. email-to-self alert the operator to take the thread.

Pure logic — the sender / airtable / notifier are injected, so it runs offline
in tests. Any reply on either channel freezes the whole sequence.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from system_b.review.state import mark_do_not_contact, mark_replied

log = logging.getLogger("system_b.webhooks")

_TAG_RE = re.compile(r"<[^>]+>")


def _plain(text: str | None) -> str:
    """Strip HTML tags to a short plain-text preview."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text)).strip()


def _lead_email(payload: dict[str, Any]) -> str:
    # EMAIL_REPLY carries the lead as to_email; be liberal about alternatives.
    return (payload.get("to_email") or payload.get("lead_email")
            or payload.get("email") or "").strip()


def _pause_best_effort(sender: Any, fields: dict[str, Any]) -> bool:
    lead_id = fields.get("smartlead_lead_id")
    campaign_id = fields.get("smartlead_campaign_id")
    if not (lead_id and campaign_id):
        return False
    try:
        sender.pause_lead(str(campaign_id), str(lead_id))
        return True
    except Exception as exc:  # noqa: BLE001 — never let a pause failure block the freeze
        log.error("pause_lead failed during freeze (%s): %s", type(exc).__name__, exc)
        return False


def handle_reply_event(
    payload: dict[str, Any], at: Any, sender: Any, notifier: Any
) -> dict[str, Any]:
    """Freeze the sequence for the replying prospect and alert the operator."""
    email = _lead_email(payload)
    if not email:
        return {"status": "ignored", "reason": "no lead email in payload"}
    row = at.find_by_email(email)
    if not row:
        log.warning("reply from unknown lead %s (campaign %s)", email, payload.get("campaign_id"))
        return {"status": "unknown_lead", "email": email}

    fields = row["fields"]
    rid = row["id"]
    paused = _pause_best_effort(sender, fields)

    body_preview = _plain(payload.get("preview_text") or payload.get("reply_body"))
    replied_at = (payload.get("time_replied") or "")[:10] or None
    mark_replied(at, rid, reply_body=body_preview[:2000] or None, replied_at=replied_at)

    firm = fields.get("firm_name", email)
    notifier.notify(
        f"🔔 Reply from {firm} ({email}) — take the thread",
        f"{firm} replied to your outbound.\n\n"
        f"email: {email}\n"
        f"subject: {payload.get('subject', '')}\n"
        f"when: {payload.get('time_replied', '')}\n\n"
        f"preview: {body_preview[:800]}\n\n"
        f"the sequence is frozen (paused in Smartlead: {paused}). "
        f"open the thread in the sending inbox and reply by hand.",
    )
    return {"status": "frozen", "record_id": rid, "email": email, "paused": paused}


def handle_unsubscribe_event(
    payload: dict[str, Any], at: Any, sender: Any, notifier: Any
) -> dict[str, Any]:
    """B6 — opt-out: pause + mark do_not_contact so the prospect is never touched
    again on any channel."""
    email = _lead_email(payload)
    if not email:
        return {"status": "ignored", "reason": "no lead email in payload"}
    row = at.find_by_email(email)
    if not row:
        return {"status": "unknown_lead", "email": email}
    fields = row["fields"]
    rid = row["id"]
    _pause_best_effort(sender, fields)
    mark_do_not_contact(at, rid, reason="unsubscribed via Smartlead")
    return {"status": "do_not_contact", "record_id": rid, "email": email}
