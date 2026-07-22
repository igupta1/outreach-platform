"""Track B sequence layer — generation, approval-send, and the quota scheduler.

The gift/copy/review core is unchanged; this package wires it to the sender:
  * generate.py   — B3: draft the first touch and the dynamic follow-ups
  * send.py       — B1/B2: on approve, push to the platform and advance the stage
  * scheduler.py  — B7: the quota-driven daily run (due follow-ups first)

Nothing here talks to Smartlead directly — it goes through `EmailSender`.
"""

from __future__ import annotations

from system_b.sequence.scheduler import (
    find_due_followups,
    find_new_prospects,
    guard_unready_followups,
    quota_run,
)
from system_b.sequence.send import approve_and_send

__all__ = [
    "quota_run",
    "find_due_followups",
    "find_new_prospects",
    "guard_unready_followups",
    "approve_and_send",
]
