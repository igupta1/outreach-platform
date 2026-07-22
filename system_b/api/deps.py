"""Dependency wiring for the Track H service.

`default_deps` returns the shared (airtable, sender, notifier) triple, built
lazily and cached so a long-lived server reuses one Airtable/Smartlead client.
Tests pass their own provider to `create_app`, so nothing here touches the
network under test.
"""

from __future__ import annotations

from typing import Any

_cache: dict[str, Any] = {}


def default_deps() -> tuple[Any, Any, Any]:
    if "deps" not in _cache:
        from system_b.clients.airtable_client import AirtableClient
        from system_b.notify import default_notifier
        from system_b.sending import SmartleadSender

        _cache["deps"] = (AirtableClient(), SmartleadSender(), default_notifier())
    return _cache["deps"]
