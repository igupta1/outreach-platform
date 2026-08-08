"""Shared test setup.

`system_b.config` loads the dev `system_b/.env` at import, which may set
inventory-source env (e.g. `LEADGEN_BLOB_BASE_URL`). Clear those before every
test so the suite is hermetic — a test that wants a source sets it explicitly.
"""

from __future__ import annotations

import pytest

_INVENTORY_ENV = (
    "LEADGEN_BLOB_BASE_URL",
    "LEADGEN_INVENTORY_DIR",
    "LEADGEN_ALLOW_STALE",
    "LEADGEN_MAX_INVENTORY_AGE_DAYS",
)


@pytest.fixture(autouse=True)
def _isolate_inventory_env(monkeypatch):
    for key in _INVENTORY_ENV:
        monkeypatch.delenv(key, raising=False)
    yield
