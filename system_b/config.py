"""Env loading + constants for System B.

One source of truth. Secrets come from system_b/.env (gitignored);
constants (caps, windows, review capacity) live here.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

# --- Secrets (from system_b/.env) ---
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Prospects")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SCRAPER_BASE_URL = os.environ.get(
    "SCRAPER_BASE_URL", "https://www.ishaangpta.com"
).rstrip("/")

# --- Constants (spec Part 5 / Step 11) ---
SCRAPER_CACHE_TTL_S = 120        # ~2 min per the spec
GIFT_TARGET = 3                  # 3 best, 2 better, 1 fine
REVIEW_CAPACITY_PER_DAY = 12     # 10-15 early on
DAILY_SEND_CAP = 25              # 20-30/day
FRESH_WINDOW_DAYS = 30
STALE_WINDOW_DAYS = 60           # dead > 60d, never served


def require(*names: str) -> None:
    """Raise if any named secret is blank — used by scripts that touch
    live services (M0 acceptance, later senders)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(
            f"Missing required env var(s) in system_b/.env: {', '.join(missing)}"
        )
