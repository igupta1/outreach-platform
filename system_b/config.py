"""Env loading + constants for System B.

One source of truth. The secret (OpenAI) comes from system_b/.env (gitignored);
constants (gift target, freshness window, scraper cache) live here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


# --- Secrets (from system_b/.env) ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Retained only for the generic ScraperClient default; inventory no longer
# routes through this website endpoint (it reads Vercel Blob directly).
SCRAPER_BASE_URL = os.environ.get(
    "SCRAPER_BASE_URL", "https://www.ishaangpta.com"
).rstrip("/")

# Lead inventory source env (read at call time in clients/inventory.py so tests
# can monkeypatch them): LEADGEN_BLOB_BASE_URL (primary, the public Vercel Blob
# base), LEADGEN_INVENTORY_DIR (offline folder fallback), LEADGEN_MAX_INVENTORY_AGE_DAYS
# and LEADGEN_ALLOW_STALE (freshness guard).

# --- Constants ---
SCRAPER_CACHE_TTL_S = 120        # ~2 min per-response cache in the scraper client
FRESH_WINDOW_DAYS = 30           # a signal newer than this reads as "fresh"


def require(*names: str) -> None:
    """Raise if any named secret is blank — used by the CLI before it does live
    work (LLM calls, live inventory fetch)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(
            f"Missing required env var(s) in system_b/.env: {', '.join(missing)}"
        )
