"""Track H — the single deployed FastAPI service.

Serves BOTH:
  * the Smartlead reply webhook (Track B / B5, token-guarded)  — /webhooks/*
  * the operator UI API (bearer-auth)                          — /api/*
plus a background task that runs the follow-up timing guard (B5) on an interval.

One process, one deploy (Railway/Render). Clients are lazily built via
`deps_provider`, overridable in tests, so importing/constructing touches no network.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from system_b import config
from system_b.api.deps import default_deps
from system_b.api.routes import build_api_router
from system_b.webhooks.app import build_webhook_router

log = logging.getLogger("system_b.api")


async def _guard_loop(deps_provider: Callable[[], tuple[Any, Any, Any]]) -> None:
    """Periodically pause any lead whose follow-up isn't ready before its step
    timer fires (B5). Runs the sync guard in a thread so it never blocks the loop."""
    from system_b.sequence import guard_unready_followups

    while True:
        try:
            at, sender, _ = deps_provider()
            paused = await asyncio.get_event_loop().run_in_executor(
                None, lambda: guard_unready_followups(at, sender)
            )
            if paused:
                log.warning("timing guard paused %d unready follow-up(s): %s", len(paused), paused)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a guard hiccup must not kill the server
            log.error("guard loop error (%s): %s", type(exc).__name__, exc)
        await asyncio.sleep(config.GUARD_INTERVAL_S)


def create_app(
    deps_provider: Callable[[], tuple[Any, Any, Any]] = default_deps,
    *,
    enable_scheduler: bool | None = None,
) -> FastAPI:
    if enable_scheduler is None:
        enable_scheduler = config.SCHEDULER_ENABLED
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(_guard_loop(deps_provider)) if enable_scheduler else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()

    app = FastAPI(title="System B — operator service", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.UI_ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(build_webhook_router(deps_provider))   # token-guarded, no bearer
    app.include_router(build_api_router(deps_provider))       # bearer-auth
    return app


# For `uvicorn system_b.api.app:app` in production.
app = create_app()
