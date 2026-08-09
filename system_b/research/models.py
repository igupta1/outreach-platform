"""Data structures for Step 2a prospect research."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Evidence:
    """A single verified fact: `text` appears word-for-word at `url`."""
    kind: str            # "phrase" (a stated niche) | "client" (a named client)
    text: str            # the verbatim quote / client name
    url: str             # the fetched page it was found on


@dataclass
class ResearchResult:
    classification: str                       # "niched" | "generalist"
    match_param: tuple[str, str] | None       # ("niche","dental") / ("industry","healthcare") / None
    niche_phrase: str | None                  # exact stated phrase, saved (may be kept even when generalist)
    niche_source: str                         # "site" | "client_list" | "" (generalist)
    evidence: list[Evidence] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    # Change 2: every verbatim-verified, mappable stated industry (Gate A). The
    # tiering resolver tries each against the live leads (Gate B) and claims the
    # best-supplied one. `match_param` above is just the first / primary.
    candidate_match_params: list[tuple[str, str]] = field(default_factory=list)
    # The verbatim phrase behind each candidate, aligned 1:1 with
    # candidate_match_params, so the CLAIMED niche's phrase (not the first stated
    # one) is what the review card shows — no "biotechnology -> nonprofit" contradiction.
    candidate_phrases: list[str] = field(default_factory=list)
    # "single" (one clear stated focus) | "multiple" (lists several served
    # industries/client types) | "" (generalist). Drives sole vs one_of_several.
    exclusivity: str = ""
    # The subset of verified client names that copy may NAME. Verbatim on the
    # site is not enough — a name in a footer could be a partner, a vendor, or
    # an "as seen in" logo, and "you worked with X" would then be false. Only
    # names found on a page that presents them AS clients land here, so this is
    # empty far more often than `evidence` has client rows.
    nameable_clients: list[str] = field(default_factory=list)
