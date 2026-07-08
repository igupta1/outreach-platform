"""Data structures for the gift engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from system_b.models import Lead


@dataclass
class Prospect:
    """A fractional-CFO firm we're building a gift for. `match_param` is the
    output of Step 2b: ("niche", "dental") or ("industry", "healthcare"),
    or None for a generalist / unmapped niche."""
    firm_name: str
    city: str | None = None
    state: str | None = None
    classification: str = "generalist"      # "niched" | "generalist"
    match_param: tuple[str, str] | None = None
    niche_phrase: str | None = None          # their exact words (framing 5a)
    niche_source: str = "site"               # "site" | "client_list" (framing 5a)
    first_name: str | None = None            # contact first name for the greeting
    sent_lead_ids: list[str] = field(default_factory=list)


@dataclass
class Gift:
    leads: list[Lead]                        # ordered, best first
    best_lead: Lead
    gift_size: int                           # 1, 2, or 3
    all_niche: bool
    geo_level: str                           # "city" | "state" | "none"
    subject_shape: str                       # "singular" | "plural"
    what_category: str                       # "raised" | "hiring" | "mixed"
    best_lead_level: int | None              # match level of the best lead (1-5 / 1-2)
