"""F2 — LinkedIn copy. LIFTED verbatim from the spec (Steps 8-9), NOT generated
and NOT via describe_leads. DMs point back at the email thread; they describe no
leads. Honesty gate: "[N] [niche] companies" only when all_niche is True.

The default builders here are the CFO templates; a pack overrides them via
NichePack.li_dm_1 / li_dm_2 (per-pack templates, same pattern as email copy).
"""

from __future__ import annotations

from typing import Any

from system_b.gift.models import Prospect


def connection_request() -> str:
    """Day-0 LinkedIn connection request — blank, no note."""
    return ""


def _who(ctx: dict[str, Any]) -> str:
    n = ctx["n"]
    if ctx.get("all_niche") and ctx.get("niche"):
        return f"{n} {ctx['niche']} companies"
    return f"{n} companies"


def cfo_dm_1(prospect: Prospect, ctx: dict[str, Any]) -> str:
    """DM #1 — the spam-check nudge, with the cfo_wanted add-on when the email's
    best lead was a fractional-CFO posting."""
    first = (prospect.first_name or "there").lower()
    text = (
        f"hey {first}, sent you {_who(ctx)} over email that are showing they need "
        f"finance help right now. did it land in spam? happy to resend here."
    )
    if ctx.get("best_cfo_company"):
        text += f" {ctx['best_cfo_company']} is even hiring a fractional cfo."
    return text


def cfo_dm_2(prospect: Prospect) -> str:
    """DM #2 — the graceful close."""
    return (
        "no stress if this isn't a priority. if sourcing ever becomes a pain, the "
        "feed is there. good luck with the pipeline either way."
    )


def build_dm(step: str, prospect: Prospect, ctx: dict[str, Any], *, pack) -> str:
    """Render the LinkedIn DM for `step` (dm_1|dm_2) using the pack's template
    (defaults to the CFO copy)."""
    if step == "dm_1":
        fn = (pack.li_dm_1 if pack and pack.li_dm_1 else cfo_dm_1)
        return fn(prospect, ctx)
    if step == "dm_2":
        fn = (pack.li_dm_2 if pack and pack.li_dm_2 else cfo_dm_2)
        return fn(prospect)
    raise ValueError(f"unknown LinkedIn DM step {step!r}")
