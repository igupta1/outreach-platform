"""Which firm was handed which organization -- so two firms in one area never
get the same one.

Two finance firms in the same market pitching the same nonprofit is the one
collision a recipient can discover on their own (they talk, and the org tells
them), and it makes the list look like a resold spreadsheet. So every lead a
sequence uses is recorded against the firm and its REGION, and a later prospect
in that region is never shown it.

## Region is the STATE, deliberately

The rule is "one metro", but a prospect carries only Apollo's city and state,
and mapping a city to its metro area needs a Census place-to-CBSA crosswalk
this repo does not have. A state contains its metros, so keying on state is
strictly STRONGER than the rule -- it can block a lead a metro key would allow,
never the reverse -- and the inventories are deep enough (4,000+ nonprofits)
that the extra blocking costs a swap, not a gift. A prospect with no state
shares the empty region only with other prospects that have none.

## Identity, not lead id

Lead ids are per-emit row numbers and change every refresh. `Lead.identity`
(an EIN, a CRD, a domain) is the organization, so that is what is recorded.

The file is append-only and holds no status: whether the email was sent or
answered lives with the sender, not here.
"""

from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from system_b.gift.engine import norm_state

log = logging.getLogger("system_b.gift")

COLUMNS = ["lead", "region", "firm", "allocated_on"]
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "lead-allocations.csv"


def _firm(name: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split())


def region_of(state: str | None) -> str:
    return norm_state(state)


class Allocations:
    def __init__(self) -> None:
        # identity -> region -> firms that hold it there
        self._held: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self._pending: list[dict[str, str]] = []

    @classmethod
    def load(cls, path: Path) -> Allocations:
        """An unreadable or missing file is an empty ledger, logged: blocking
        is a courtesy between prospects, and losing it must not stop a run."""
        a = cls()
        if not path.exists():
            return a
        try:
            with path.open(newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("lead"):
                        a._held[row["lead"]][row.get("region") or ""].add(row.get("firm") or "")
        except (OSError, csv.Error) as exc:
            log.warning("allocations: could not read %s (%s) — nothing blocked", path, exc)
        return a

    def blocked(self, firm: str | None, state: str | None) -> frozenset[str]:
        """Identities already handed to a DIFFERENT firm in this firm's region."""
        me, region = _firm(firm), region_of(state)
        return frozenset(
            ident for ident, regions in self._held.items()
            if regions.get(region) and regions[region] - {me}
        )

    def record(self, identities: Iterable[str | None], firm: str | None,
               state: str | None, today: date) -> None:
        """Hold these for the firm now (so the rest of THIS run respects them)
        and queue them for `save`."""
        me, region = _firm(firm), region_of(state)
        for ident in identities:
            if not ident or me in self._held[ident][region]:
                continue
            self._held[ident][region].add(me)
            self._pending.append({"lead": ident, "region": region, "firm": me,
                                  "allocated_on": today.isoformat()})

    def save(self, path: Path) -> int:
        """Append what this run recorded. Returns the number of rows written."""
        if not self._pending:
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            if new:
                w.writeheader()
            w.writerows(self._pending)
        n, self._pending = len(self._pending), []
        return n
