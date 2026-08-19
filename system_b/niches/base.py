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
    funding_phrase: Callable[..., str] | None   # (lead) -> templated raise line, or None
    priority_flag: str | None               # review/copy flag when a priority-signal lead is present

    # --- LinkedIn DM voice (read by copy/linkedin.py) ---
    # Who the tool was built for, as the DM names them: "fractional cfos",
    # "msps". Reads "built this one for {dm_audience}."
    dm_audience: str
    # The role a gift lead posted, singular WITH its article and plural without:
    # "a finance role" / "finance roles". Two fields rather than one derived
    # from the other because the article is not mechanical ("an it role").
    dm_role_singular: str
    dm_role_plural: str

    # descriptor for the fallback follow-up bump, e.g. "a finance-need signal"
    followup_signal: str = "a buying signal"


def default_pack() -> NichePack:
    """The CFO pack, imported at call time so core modules never import a pack
    at load time (avoids a copy/engine <-> niches import cycle)."""
    from system_b.niches.cfo import CFO_PACK

    return CFO_PACK


def pack_for(key: str | None) -> NichePack:
    """Resolve a pack by key (the row's `niche_pack`). Lazy imports keep this a
    leaf module. Unknown / blank -> the CFO default."""
    k = (key or "cfo").strip().lower()
    # bookkeeping is no longer an alias for accounting: they are two rungs of
    # the finance ladder with different leads, different buyers and different
    # words for who the tool was built for.
    if k == "bookkeeping":
        from system_b.niches.bookkeeping import BOOKKEEPING_PACK
        return BOOKKEEPING_PACK
    if k == "accounting":
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
