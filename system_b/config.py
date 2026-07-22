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


def _parse_map(raw: str) -> dict[str, str]:
    """Parse a "key:value,key:value" env string into a dict. Blank -> {}.
    Used for the per-niche Smartlead campaign mapping."""
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        k, v = pair.split(":", 1)
        if k.strip() and v.strip():
            out[k.strip()] = v.strip()
    return out


# --- Secrets (from system_b/.env) ---
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
AIRTABLE_TABLE_NAME = os.environ.get("AIRTABLE_TABLE_NAME", "Prospects")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SCRAPER_BASE_URL = os.environ.get(
    "SCRAPER_BASE_URL", "https://www.ishaangpta.com"
).rstrip("/")

# --- Sending (Track B / Smartlead) ---
SMARTLEAD_API_KEY = os.environ.get("SMARTLEAD_API_KEY", "")
SMARTLEAD_BASE_URL = os.environ.get(
    "SMARTLEAD_BASE_URL", "https://server.smartlead.ai/api/v1"
).rstrip("/")
# Per-niche campaign ids, e.g. "cfo:1234,accounting:5678,mssp:9012" ->
# {"cfo": "1234", ...}. Keys are the five niche packs: accounting, cfo, mssp,
# msp, cloud.
SMARTLEAD_CAMPAIGN_IDS = _parse_map(os.environ.get("SMARTLEAD_CAMPAIGN_IDS", ""))

# --- Reply webhook (Track B / B5) ---
# Smartlead does NOT sign its webhooks, so the public receiver is guarded by a
# shared token in the URL (?token=...). WEBHOOK_PUBLIC_URL is where Smartlead
# should POST — used when registering the webhook via the API.
WEBHOOK_TOKEN = os.environ.get("WEBHOOK_TOKEN", "")
WEBHOOK_PUBLIC_URL = os.environ.get("WEBHOOK_PUBLIC_URL", "")

# --- Operator UI (Track H) ---
# Single-user bearer auth for the /api/* routes; CORS origins for the React app;
# how often the background scheduler runs the follow-up timing guard.
UI_AUTH_TOKEN = os.environ.get("UI_AUTH_TOKEN", "")
UI_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "UI_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",") if o.strip()
]
GUARD_INTERVAL_S = int(os.environ.get("GUARD_INTERVAL_S", "3600") or "3600")
# The background timing-guard scheduler; disable for safe local poking.
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1").lower() not in ("0", "false", "no", "")

# --- Operator alert on reply (Track B / B5) ---
# Preference order: ntfy.sh push (if NTFY_TOPIC set) -> SMTP email -> logging.
# ntfy is free, account-less, instant to the phone; email stays as a fallback.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_PRIORITY = os.environ.get("NTFY_PRIORITY", "high")

# Email fallback: if SMTP is unset the notifier degrades to logging (never
# blocks a freeze).
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")
ALERT_EMAIL_FROM = os.environ.get("ALERT_EMAIL_FROM", "") or os.environ.get("SMTP_USER", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# --- Constants (spec Part 5 / Step 11) ---
SCRAPER_CACHE_TTL_S = 120        # ~2 min per the spec
GIFT_TARGET = 3                  # 3 best, 2 better, 1 fine
REVIEW_CAPACITY_PER_DAY = 12     # 10-15 early on
DAILY_SEND_CAP = 25              # 20-30/day
FRESH_WINDOW_DAYS = 30
STALE_WINDOW_DAYS = 60           # dead > 60d, never served

# Sequence cadence (Track B / A6 / B3). Smartlead step delays in days between
# the previous step and this one; step 1 is the first touch (delay 0).
SEQUENCE_STEP_GAP_DAYS = {1: 0, 2: 3, 3: 4}
SEQUENCE_STEPS = 3


def require(*names: str) -> None:
    """Raise if any named secret is blank — used by scripts that touch
    live services (M0 acceptance, later senders)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(
            f"Missing required env var(s) in system_b/.env: {', '.join(missing)}"
        )
