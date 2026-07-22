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

from system_b.cadence import DEFAULT_CADENCE, Step


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

    # --- Track F (LinkedIn + unified cadence) ---
    # cadence is the ordered email+LinkedIn step list (tunable per pack). The DM
    # builders are LIFTED templates (not LLM-generated); None -> the CFO defaults.
    cadence: tuple[Step, ...] = DEFAULT_CADENCE
    li_dm_1: Callable[..., str] | None = None   # (prospect, ctx) -> DM #1 text
    li_dm_2: Callable[..., str] | None = None   # (prospect) -> DM #2 text


def default_pack() -> NichePack:
    """The CFO pack, imported at call time so core modules never import a pack
    at load time (avoids a copy/engine <-> niches import cycle)."""
    from system_b.niches.cfo import CFO_PACK

    return CFO_PACK


def pack_for(key: str | None) -> NichePack:
    """Resolve a pack by key (the row's `niche_pack`). Lazy imports keep this a
    leaf module. Unknown / blank -> the CFO default."""
    k = (key or "cfo").strip().lower()
    if k in ("accounting", "bookkeeping"):   # bookkeeping kept as a legacy alias
        from system_b.niches.accounting import ACCOUNTING_PACK
        return ACCOUNTING_PACK
    if k == "msp":
        from system_b.niches.it_provider import MSP_PACK
        return MSP_PACK
    if k == "mssp":
        from system_b.niches.it_provider import MSSP_PACK
        return MSSP_PACK
    if k == "cloud":
        from system_b.niches.it_provider import CLOUD_PACK
        return CLOUD_PACK
    return default_pack()
