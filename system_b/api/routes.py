"""The /api/* routes for the operator UI (Track H). Thin wrappers over the
system_b library; Airtable stays the datastore.

Screens: H1 upload + queue, H2 quota generate, H3 flashcard review + actions,
H4 LinkedIn queue. All behind single-user bearer auth.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from system_b.api import service
from system_b.api.auth import require_auth
from system_b.api.jobs import get_job, start_generate
from system_b.review import apply_decision
from system_b.sequence import approve_and_send
from system_b.sequence import linkedin as li


class GenerateBody(BaseModel):
    emails: int = 12
    linkedin: int = 0
    pack: str = "cfo"


class EditBody(BaseModel):
    subject: str = ""
    body: str


class ApproveBody(BaseModel):
    message: str | None = None


def build_api_router(deps_provider: Callable[[], tuple[Any, Any, Any]]) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

    def _at():
        return deps_provider()[0]

    def _sender():
        return deps_provider()[1]

    # --- H1: upload + queue ------------------------------------------------

    @router.post("/prospects/upload")
    async def upload(file: UploadFile = File(...), niche: str = Form("cfo")) -> dict[str, Any]:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        return service.ingest_csv(_at(), data, niche)

    @router.get("/prospects")
    def prospects() -> dict[str, Any]:
        rows = service.queue(_at())
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"counts": counts, "prospects": rows}

    @router.post("/prospects/{record_id}/eligible")
    def set_eligible(record_id: str, eligible: bool = True) -> dict[str, Any]:
        # The operator's explicit send-safety flip (the hard gate).
        _at().update(record_id, {"eligible_for_send": eligible})
        return {"status": "ok", "record_id": record_id, "eligible_for_send": eligible}

    # --- H2: quota generate ------------------------------------------------

    @router.post("/generate")
    def generate(body: GenerateBody) -> dict[str, Any]:
        job = start_generate(_at(), emails=body.emails, linkedin=body.linkedin, pack=body.pack)
        return job.as_dict()

    @router.get("/generate/status")
    def generate_status(job_id: str) -> dict[str, Any]:
        job = get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job.as_dict()

    # --- H3: flashcard review + actions ------------------------------------

    @router.get("/cards")
    def cards(channel: str | None = None) -> dict[str, Any]:
        if channel is not None and channel not in ("email", "linkedin"):
            raise HTTPException(status_code=400, detail="channel must be email or linkedin")
        items, total = service.pending_cards(_at(), channel)
        # count = the walk length for "card N of M"; total = all pending channels.
        return {"count": len(items), "total": total, "channel": channel, "cards": items}

    @router.post("/cards/{record_id}/approve")
    def approve(record_id: str, body: ApproveBody | None = None, channel: str = "email") -> dict[str, Any]:
        at = _at()
        # Any failure — the eligible_for_send gate, a Smartlead error, etc. —
        # surfaces as approved=false and leaves the card pending. The push (email)
        # happens BEFORE any Airtable write, so we NEVER report approved-but-unsent.
        try:
            if channel == "linkedin":
                return li.approve_linkedin(at, record_id)
            msg = body.message if body else None
            res = approve_and_send(at, _sender(), record_id, edited_message=msg)
            return {"approved": True, "pushed": True, "record_id": record_id, **res}
        except Exception as exc:  # noqa: BLE001
            return {"approved": False, "pushed": False, "record_id": record_id,
                    "error": f"{type(exc).__name__}: {exc}"}

    @router.post("/cards/{record_id}/reject")
    def reject(record_id: str, channel: str = "email") -> dict[str, Any]:
        if channel == "linkedin":
            return li.reject_linkedin(_at(), record_id)
        apply_decision(_at(), record_id, "reject")
        return {"status": "rejected", "record_id": record_id}

    @router.post("/cards/{record_id}/edit")
    def edit(record_id: str, body: EditBody, channel: str = "email") -> dict[str, Any]:
        # Re-run the copy honesty guarantees over the human edit (H/F): strip any
        # dollar amount, warn on date phrases, store the cleaned text.
        if channel == "linkedin":
            return li.edit_linkedin(_at(), record_id, body.body)
        from system_b.copy.honesty import lint_free_text

        clean_body, warnings = lint_free_text(body.body)
        message = f"Subject: {body.subject}\n\n{clean_body}"
        apply_decision(_at(), record_id, "edit", edited_message=message)
        return {"status": "edited", "record_id": record_id,
                "warnings": warnings, "cleaned_body": clean_body}

    @router.post("/cards/{record_id}/skip")
    def skip(record_id: str) -> dict[str, Any]:
        # Stays pending — nothing to write; the UI just advances to the next card.
        return {"status": "skipped", "record_id": record_id}

    # --- H4: LinkedIn queue ------------------------------------------------

    @router.get("/linkedin/queue")
    def linkedin() -> dict[str, Any]:
        items = service.linkedin_queue(_at())
        return {"count": len(items), "items": items}

    @router.post("/linkedin/{record_id}/connection")
    def connection(record_id: str, accepted: bool = True) -> dict[str, Any]:
        # F3: the manual gate for DM steps (no safe LinkedIn API).
        _at().update(record_id, {"connection_accepted": accepted})
        return {"status": "ok", "record_id": record_id, "connection_accepted": accepted}

    @router.post("/linkedin/{record_id}/connect_sent")
    def connect_sent(record_id: str) -> dict[str, Any]:
        return li.mark_connect_sent(_at(), record_id)

    @router.post("/linkedin/{record_id}/sent")
    def linkedin_sent(record_id: str) -> dict[str, Any]:
        return li.mark_dm_sent(_at(), record_id)

    return router
