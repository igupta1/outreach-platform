"""One fact per lead, from its own record (2026-11-05, the user: "add one fact
per lead from the public record").

The gift used to print a name and a city and nothing else, and a prospect
answered "not just a database". The record already says what makes a lead
worth calling: how big the award or loan is and who gave it, how much the
charity takes in, how many people are in the plan, who runs it. One of those,
read by code from the record's own fields and formatted here; never written
by a model, never estimated, never added up across records.

Order: a dollar figure with its source (award, loan, late contributions,
filed revenue), then a plan's size, then a named contact with a plain role.
"" when the record has none of these.
"""

from __future__ import annotations

import re

from system_b.models import Lead

# Roles worth printing beside a name. A source's own wording ("Signed the Form
# 5500 as plan administrator", "AR") is not a role a reader can use.
_ROLE_RE = re.compile(
    r"^(?:owner|co-owner|founder|co-founder|ceo|cfo|coo|president|vice president|"
    r"executive director|interim executive director|director|managing member|"
    r"managing partner|partner|principal|general manager|manager|"
    r"accounting manager|finance director|director of finance|controller|treasurer|"
    r"administrator|plan administrator)$", re.I)

# "Department of Veterans Affairs" -> "veterans affairs"; Defense awards name
# the service instead ("Department of the Army" -> "army").
_AGENCY_DROP = re.compile(r"^(?:u\.?s\.?\s+)?(?:department of (?:the )?)", re.I)


def money(v: object) -> str:
    """$988k, $1.2m, $56k, $900. "" for anything that is not a positive number."""
    if isinstance(v, bool):
        return ""
    try:
        x = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if x <= 0:
        return ""
    if x >= 1_000_000:
        m = x / 1_000_000
        return f"${m:.1f}m".replace(".0m", "m") if m < 100 else f"${m:.0f}m"
    if x >= 1_000:
        return f"${x / 1000:.0f}k"
    return f"${x:.0f}"


def agency(p: dict) -> str:
    top = str(p.get("awarding_agency") or "").strip()
    sub = str(p.get("awarding_sub_agency") or "").strip()
    name = sub if top.lower() == "department of defense" and sub else top
    short = _AGENCY_DROP.sub("", name).strip().lower()
    # "transportation" alone reads as an industry: "transportation dept".
    if short and short != name.lower() and " " not in short \
            and short not in ("army", "navy", "defense"):
        return f"{short} dept"
    return short


def _payload(lead: Lead) -> dict:
    out: dict = {}
    for s in lead.signals or []:
        out.update(s.payload or {})
    return out


def _contact(lead: Lead) -> str:
    name = " ".join((lead.contact_name or "").split())
    title = " ".join((lead.contact_title or "").split())
    if not name or not title or not _ROLE_RE.match(title):
        return ""
    if name.isupper() or name.islower():
        name = name.title()
    return f"{name}, {title.lower()}"


def record_fact(lead: Lead) -> str:
    p = _payload(lead)
    award = money(p.get("award_amount"))
    if award:
        who = agency(p)
        return f"{award}, {who}" if who else award
    loan = money(p.get("loan_amount"))
    if loan:
        return f"{loan} loan"
    if (lead.signal_type or "") == "plan_late_contributions":
        late = money(p.get("amount"))
        if late:
            return f"{late} in late contributions"
    revenue = money(p.get("total_revenue"))
    if revenue and (lead.signal_type or "").startswith("nonprofit"):
        return f"{revenue} in revenue"
    n = p.get("participants_eoy")
    if (lead.signal_type or "").startswith(("plan_", "welfare_")) and isinstance(n, (int, float)) \
            and not isinstance(n, bool) and n > 0:
        return f"{int(n)} in the plan"
    return _contact(lead)
