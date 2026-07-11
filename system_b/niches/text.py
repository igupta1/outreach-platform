"""Tiny shared copy helpers for niche packs."""

from __future__ import annotations


def noun(n: int, singular: str, plural: str | None = None) -> str:
    """The noun form for a count: `noun(1, "carrier")` -> "carrier",
    `noun(3, "company", "companies")` -> "companies". Count is rendered
    separately by the caller (e.g. f"{n} new {noun(n, 'carrier')}")."""
    return singular if n == 1 else (plural or singular + "s")
