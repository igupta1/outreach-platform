"""F1 — the unified email+LinkedIn cadence, as data.

One ordered step list per prospect, walked by the scheduler. Day offsets are
absolute from Day 0 (the day Email #1 is sent, stored as sequence_started_at).
Gates decide whether a step may fire. Reply on EITHER channel freezes the whole
sequence (the row's `frozen` flag; enforced by the scheduler skipping frozen
rows), so no gate has to encode "no reply" beyond the frozen check.

DECIDED default cadence (tunable per pack via NichePack.cadence):
  Day 0  — Email #1  + LinkedIn connection request (blank)
  Day 3  — Email #2  (new lead, in-thread)
  Day 5  — LinkedIn DM #1  (only if connection accepted)
  Day 7  — Email #3  (new lead, in-thread, final email)
  Day 10 — LinkedIn DM #2  (only if connection accepted)
"""

from __future__ import annotations

from dataclasses import dataclass

# Gate keys the scheduler understands.
GATE_CONNECTED = "connected"          # connection_accepted must be True


@dataclass(frozen=True)
class Step:
    key: str          # unique step id
    channel: str      # "email" | "linkedin"
    kind: str         # email_1 | email_followup | connect | dm_1 | dm_2
    day: int          # absolute day offset from Day 0
    gate: str | None  # None, or GATE_CONNECTED


DEFAULT_CADENCE: tuple[Step, ...] = (
    Step("email_1", "email", "email_1", 0, None),
    Step("li_connect", "linkedin", "connect", 0, None),
    Step("email_2", "email", "email_followup", 3, None),
    Step("li_dm_1", "linkedin", "dm_1", 5, GATE_CONNECTED),
    Step("email_3", "email", "email_followup", 7, None),
    Step("li_dm_2", "linkedin", "dm_2", 10, GATE_CONNECTED),
)

# LinkedIn DM progression: what the last completed LinkedIn step implies is next.
_NEXT_DM = {"": "dm_1", "connect": "dm_1", "dm_1": "dm_2"}


def linkedin_steps(cadence: tuple[Step, ...] = DEFAULT_CADENCE) -> list[Step]:
    return [s for s in cadence if s.channel == "linkedin" and s.kind in ("dm_1", "dm_2")]


def next_dm_step(li_progress: str | None) -> str | None:
    """The next LinkedIn DM to draft given the last LinkedIn step done."""
    return _NEXT_DM.get(li_progress or "")


def day_for(kind: str, cadence: tuple[Step, ...] = DEFAULT_CADENCE) -> int | None:
    for s in cadence:
        if s.kind == kind:
            return s.day
    return None
