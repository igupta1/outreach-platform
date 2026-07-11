"""NichePack — the per-buyer knobs the niche-agnostic core reads.

The engine (gift building) and copy scaffolding are niche-blind; everything
CFO-specific (or trucking-specific) lives in a NichePack. Core functions take
`pack=None` and lazily default to the CFO pack via `default_pack()`, so existing
call sites keep their exact behavior.

Type hints reference Gift/Prospect/Lead by name only (stringized by
`from __future__ import annotations`) so this stays a leaf module that no core
module has to import heavily — which is what keeps the copy<->niches cycle away.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class NichePack:
    key: str

    # --- signal vocabulary (read by the gift engine) ---
    signal_rank: Mapping[str, int]          # signal_type -> strength (lower = stronger)
    priority_signal: str | None             # the 3a "lead-first" signal; None = none
    raise_signals: frozenset[str]           # signals whose copy is a templated raise
    what_category: Callable[..., str]       # (leads) -> subject WHAT category

    # --- voice (read by the copy scaffolding) ---
    subject: Callable[..., str]             # (gift, prospect) -> subject line
    framing: Callable[..., str]             # (gift, prospect) -> opening framing line
    cta: Callable[..., str]                 # (gift, prospect) -> closing CTA line
    left_field: tuple[str, ...]             # 5b rotation lines
    left_field_labels: tuple[str, ...]      # aligned A/B labels
    funding_phrase: Callable[..., str] | None   # (lead) -> templated raise line, or None
    priority_flag: str | None               # review/copy flag when a priority-signal lead is present


def default_pack() -> NichePack:
    """The CFO pack, imported at call time so core modules never import a pack
    at load time (avoids a copy/engine <-> niches import cycle)."""
    from system_b.niches.cfo import CFO_PACK

    return CFO_PACK
