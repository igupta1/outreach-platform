"""B5 — the reply-webhook receiver.

`reply.py` holds the pure freeze logic (no web framework) so it's unit-testable
and reusable; `app.py` is the thin FastAPI receiver that Track H will absorb.
Importing this package does NOT require FastAPI — only `app.py` does.
"""

from __future__ import annotations

from system_b.webhooks.reply import handle_reply_event, handle_unsubscribe_event

__all__ = ["handle_reply_event", "handle_unsubscribe_event"]
