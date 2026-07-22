"""Single-user bearer auth for the /api/* routes (Track H).

A shared token (UI_AUTH_TOKEN) in an `Authorization: Bearer` header. Simple by
design — one operator, one secret. The webhook route is NOT behind this; it has
its own query-token guard (Smartlead can't send a bearer header).
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from system_b import config


def require_auth(authorization: str = Header(default="")) -> None:
    if not config.UI_AUTH_TOKEN:
        raise HTTPException(status_code=500, detail="UI_AUTH_TOKEN not configured on the server")
    token = authorization.removeprefix("Bearer ").strip()
    if token != config.UI_AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
