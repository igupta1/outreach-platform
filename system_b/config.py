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
# Hard ceiling on a JOB-posting lead entering a gift. The copy says a company
# "is looking for a controller" — present tense — and a posting that closed
# makes that false, with no way for the recipient to tell we were ever right.
# Job boards expire most postings around 30 days, so 21 keeps the claim inside
# the window where it is still very likely open. Applies to both gift rounds
# (fresh AND the stale fallback), so nothing routes around it.
MAX_JOB_LEAD_AGE_DAYS = 21

# The FRACTIONAL tier gets the full board window instead, for the same reason
# leadgen scrapes it on a 60-day cycle rather than 30 (`_FRACTIONAL_MAX_POSTING_AGE_DAYS`):
# the fractional universe is small and a fractional search runs longer than a
# full-time one — nobody backfills a part-time CFO in three weeks.
#
# This is the only lever that actually grows the fractional pool. Measured on
# live inventory, the 22-30 day bucket holds 72 more cfo and 6 more accounting
# postings that GENUINELY say fractional/interim/part-time — 47 -> 119 for cfo.
# Loosening the evidence gate instead recovers nothing: every candidate word and
# phrase was measured and every match was a duty or a benefit ("Forms 1099",
# "40 hours per Week (Full-Time)", "oversee outsourced accounting providers").
MAX_FRACTIONAL_LEAD_AGE_DAYS = 30

# Past this, a lead still enters a gift but its line carries NO relative date.
# "is looking for a fractional cfo" stays present-tense and very likely true at
# 4 weeks; "about 4 weeks ago" additionally asserts freshness, which is the half
# that stops being worth claiming. Dropping the weaker claim is what makes the
# wider window above honest rather than merely permissive.
MAX_DATED_LEAD_AGE_DAYS = 21


def require(*names: str) -> None:
    """Raise if any named secret is blank — used by the CLI before it does live
    work (LLM calls, live inventory fetch)."""
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(
            f"Missing required env var(s) in system_b/.env: {', '.join(missing)}"
        )
