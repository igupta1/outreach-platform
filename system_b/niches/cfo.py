"""The fractional-CFO niche pack.

This is the original System B behavior, packaged as a NichePack. Every field
points at the CFO bodies that already live in the core modules (engine + copy),
so this is the default pack and nothing about CFO output changes.
"""

from __future__ import annotations

from system_b.copy.email import (
    CFO_PRIORITY_FLAG,
    LEFT_FIELD,
    LEFT_FIELD_LABELS,
    _cta,
    _framing,
    _funding_phrase,
)
from system_b.copy.honesty import RAISE_SIGNALS
from system_b.copy.subject import _cfo_subject
from system_b.gift.engine import SIGNAL_RANK, _cfo_what_category
from system_b.niches.base import NichePack

CFO_PACK = NichePack(
    key="cfo",
    signal_rank=SIGNAL_RANK,
    priority_signal="cfo_wanted",
    raise_signals=RAISE_SIGNALS,
    what_category=_cfo_what_category,
    subject=_cfo_subject,
    framing=_framing,
    cta=_cta,
    left_field=tuple(LEFT_FIELD),
    left_field_labels=tuple(LEFT_FIELD_LABELS),
    funding_phrase=_funding_phrase,
    priority_flag=CFO_PRIORITY_FLAG,
)
