"""Place names that need care before they reach an email."""

from __future__ import annotations

_DC_STATES = frozenset({"dc", "district of columbia"})
_DC_CITIES = frozenset({"washington", "washington dc", "washington d c", "washington, dc",
                        "washington, d.c.", "washington d.c."})


def dc_city(city: str | None, state: str | None) -> str | None:
    """"Washington, DC" for the capital (2026-11-14: "these 3 in washington"
    read as the state). Any other city unchanged."""
    if city and (state or "").strip().lower() in _DC_STATES \
            and " ".join(city.lower().split()) in _DC_CITIES:
        return "Washington, DC"
    return city
