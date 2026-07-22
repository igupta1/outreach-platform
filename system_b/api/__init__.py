"""Track H — the operator UI backend.

ONE FastAPI service (`api/app.py`) that serves both the Smartlead reply webhook
(Track B / B5) and the UI API, plus a background timing-guard scheduler. It
wraps the existing system_b library; Airtable stays the datastore.
"""

from __future__ import annotations

from system_b.api.app import create_app

__all__ = ["create_app"]
