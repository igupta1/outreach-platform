"""The fractional-CFO niche pack.

This is the original System B behavior, packaged as a NichePack. Every field
points at the CFO bodies that already live in the core modules (engine + copy),
so this is the default pack and nothing about CFO output changes.
"""

from __future__ import annotations

from system_b.copy.email import (
    LEFT_FIELD,
    LEFT_FIELD_LABELS,
    _cta,
    _framing,
)
from system_b.copy.subject import _cfo_subject
from system_b.gift.engine import SIGNAL_RANK, _cfo_what_category
from system_b.niches.base import NichePack

CFO_PACK = NichePack(
    key="cfo",
    followup_signal="a finance-need signal",
    signal_rank=SIGNAL_RANK,
    priority_signal="job_fractional_cfo",
    raise_signals=frozenset(),   # EDGAR sources deleted — no raise claim is provable
    what_category=_cfo_what_category,
    subject=_cfo_subject,
    framing=_framing,
    cta=_cta,
    left_field=tuple(LEFT_FIELD),
    left_field_labels=tuple(LEFT_FIELD_LABELS),
    funding_phrase=None,
    # No priority flag. CFO_PRIORITY_FLAG ("google the posting and confirm
    # it's still live") fired on 21 of 23 prospects in a real run — a flag that
    # fires on 91% of cards carries no information and trains the reviewer to
    # skip the whole flag box, including the rare flags that matter. The
    # 21-day MAX_JOB_LEAD_AGE_DAYS cap now enforces the same thing structurally.
    # Removing it splits a run into 10 clean / 13 worth-a-look.
    priority_flag=None,
    dm_audience="fractional cfos",
    dm_role_singular="a finance role",
    dm_role_plural="finance roles",
)
