"""Typed lead object from System A's /api/leads.

Reconciled against the LIVE API (the source of truth), which differs
from the spec's Part 2:
  * NO `score` on the lead        -> Lead.score is always None
  * NO `finance_grade` on the lead -> Lead.finance_grade is always None
  * `date_confidence` lives on each SIGNAL, not the lead. We derive a
    lead-level value from the freshest signal (`effective_date_confidence`).

If System A later adds `score`/`finance_grade`, these fields populate
automatically (they're already declared) — no code change needed.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Signal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str | None = None
    date: str | None = None                 # ISO event date (posting/filing)
    date_confidence: str | None = None       # "high" | "low"
    plain_words_description: str | None = None


class Lead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    company: str
    domain: str | None = None
    city: str | None = None
    state: str | None = None
    industry: str | None = None              # coarse parent (~18)
    niche: str | None = None                 # granular child (~75) or null/unknown
    value_prop: str | None = None
    signal_type: str                          # cfo_wanted|double_signal|funding_only|hiring_only
    finance_grade: str | None = None          # not in live API -> None
    freshness: str | None = None              # fresh | stale
    score: float | None = None                # not in live API -> None
    date_confidence: str | None = None        # spec lead-level; live is per-signal
    signals: list[Signal] = Field(default_factory=list)

    @property
    def newest_date(self) -> str:
        """Freshest signal event date (ISO). '' when unknown → sorts last."""
        dates = [s.date for s in self.signals if s.date]
        return max(dates) if dates else ""

    @property
    def effective_date_confidence(self) -> str:
        """date_confidence of the freshest signal; defaults to 'high'."""
        if self.date_confidence:
            return self.date_confidence
        if not self.signals:
            return "high"
        newest = max(self.signals, key=lambda s: s.date or "")
        return newest.date_confidence or "high"
