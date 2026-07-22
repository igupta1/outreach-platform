"""B5 — the Smartlead webhook, as a mountable router + a standalone app.

Smartlead does not sign its webhooks, so the endpoint is guarded by a shared
token in the query string (?token=...). `build_webhook_router` is included by
BOTH the standalone webhook app and the unified Track H service, so there's one
receiver implementation.

Clients are built lazily per request via `deps_provider` (overridable in tests),
so importing this module — or constructing the app — touches no network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request

from system_b import config
from system_b.webhooks.reply import handle_reply_event, handle_unsubscribe_event

_REPLY_EVENTS = {"EMAIL_REPLY", "EMAIL_REPLIED"}
_OPTOUT_EVENTS = {"LEAD_UNSUBSCRIBED", "EMAIL_UNSUBSCRIBED", "UNSUBSCRIBED"}


def _default_deps() -> tuple[Any, Any, Any]:
    from system_b.clients.airtable_client import AirtableClient
    from system_b.notify import default_notifier
    from system_b.sending import SmartleadSender

    return AirtableClient(), SmartleadSender(), default_notifier()


def build_webhook_router(deps_provider: Callable[[], tuple[Any, Any, Any]] = _default_deps) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/smartlead")
    async def smartlead(request: Request, token: str = "") -> dict[str, Any]:
        if config.WEBHOOK_TOKEN and token != config.WEBHOOK_TOKEN:
            raise HTTPException(status_code=401, detail="bad or missing token")
        payload = await request.json()
        event = (payload.get("event_type") or payload.get("event") or "").upper()
        at, sender, notifier = deps_provider()
        if event in _REPLY_EVENTS:
            return handle_reply_event(payload, at, sender, notifier)
        if event in _OPTOUT_EVENTS:
            return handle_unsubscribe_event(payload, at, sender, notifier)
        return {"status": "ignored", "event": event}

    return router


def create_app(deps_provider: Callable[[], tuple[Any, Any, Any]] = _default_deps) -> FastAPI:
    app = FastAPI(title="System B — outreach webhooks")

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(build_webhook_router(deps_provider))
    return app


# Module-level app for `uvicorn system_b.webhooks.app:app` — no clients are
# constructed until a request actually arrives.
app = create_app()
