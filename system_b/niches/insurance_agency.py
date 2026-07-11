"""Insurance-agency router — one outreach pack, two sub-niches.

A trucking agent and a commercial P&C agent look identical on the buyer side
(both are "insurance agencies"), but they want different lead lists:
  - trucking  -> new FMCSA carriers  (trucking-leads.json)
  - p&c       -> growth / trigger-moment companies (pc-leads.json)

This module routes an agency to the right pack + inventory. For v1 the sub-niche
comes from the prospect input; `classify_subniche` is a keyword classifier that
can also be fed the agency's site text once research is wired in.
"""

from __future__ import annotations

from typing import Callable

from system_b.niches.pc import PC_PACK, pc_descriptions, pc_snapshot
from system_b.niches.trucking import TRUCKING_PACK, trucking_descriptions, trucking_snapshot

TRUCKING = "trucking"
PC = "pc"

# subniche -> (pack, snapshot(path, today=...) -> scraper, descriptions(leads) -> dict)
_ROUTES: dict[str, tuple[object, Callable[..., object], Callable[..., dict]]] = {
    TRUCKING: (TRUCKING_PACK, trucking_snapshot, trucking_descriptions),
    PC: (PC_PACK, pc_snapshot, pc_descriptions),
}

_TRUCKING_KEYWORDS = (
    "trucking", "motor carrier", "commercial auto", "fmcsa", "fleet",
    "cargo", "freight", "owner operator", "big rig", "semi",
)


def classify_subniche(text: str | None) -> str:
    """Keyword classify an agency's stated focus (or site text) → subniche.
    Defaults to P&C (the broad commercial-lines case) when nothing trucking-
    specific appears."""
    t = (text or "").lower()
    if any(k in t for k in _TRUCKING_KEYWORDS):
        return TRUCKING
    return PC


def route(subniche: str):
    """Return (pack, snapshot_fn, descriptions_fn) for a subniche.
    Unknown subniche → P&C."""
    return _ROUTES.get(subniche, _ROUTES[PC])
