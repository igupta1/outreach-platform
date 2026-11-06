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
    r"administrator|plan administrator|mgr|officer|member|managing director|chair|"
    r"chairman|chairperson|secretary|authorized official)$", re.I)
_ROLE_WORDS = {"mgr": "manager"}
# A lead whose named contact is its own CFO reads as one that already has
# finance help (2026-11-05): never printed.
_FINANCE_ROLE_RE = re.compile(r"\b(?:cfo|controller|treasurer|finance|accounting)\b", re.I)

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
    branch = str(p.get("branch") or "")
    if "National Institutes of Health" in branch:
        return "nih"
    if "National Science Foundation" in branch or p.get("agency") == "National Science Foundation":
        return "nsf"
    top = str(p.get("awarding_agency") or p.get("agency") or "").strip()
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
    if not name or not title or not _ROLE_RE.match(title) or _FINANCE_ROLE_RE.search(title):
        return ""
    if name.isupper() or name.islower():
        name = name.title()
    return f"{name}, {_ROLE_WORDS.get(title.lower(), title.lower())}"


def record_fact(lead: Lead) -> str:
    p = _payload(lead)
    award = money(p.get("award_amount"))
    if award:
        who = agency(p)
        return f"{award}, {who}" if who else award
    loan = money(p.get("loan_amount"))
    if loan:
        # The borrower's business, from the loan record's own NAICS title.
        what = _industry(p.get("naics_description"))
        return f"{loan} loan" + (f", {what}" if what else "")
    grant = money(p.get("subaward_amount"))
    if grant:
        return f"{grant} grant"
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
    t = lead.signal_type or ""
    if t == "construction_large_permit":
        job = money(p.get("headline_value"))
        if job:
            return f"{job} job"
    if t == "sam_new_entity_registration":
        from system_b.gift.fit import naics_title

        what = _industry(naics_title(p.get("naics")))
        if what:
            return what
    if t.startswith("fda_") and p.get("panel"):
        panel = str(p["panel"]).split(",")[0].strip().lower()
        if panel and len(panel) <= 25:
            return f"{panel} device"
    # What the licence or permit is for, in the regulator's own words.
    if t.startswith("liquor_license_"):
        label = str(p.get("license_label") or "")
        if re.search(r"eating place|restaurant", label, re.I):
            return "restaurant license"
        if re.search(r"beer and wine|wine and malt|beer & wine", label, re.I):
            return "beer and wine license"
    if t in ("tx_new_sales_tax_permit", "tx_late_sales_tax_registration", "new_business_expanding"):
        what = _industry(p.get("naics_label") or p.get("naics_title") or p.get("naics_description"))
        if what:
            return what
    if t in ("new_practice_npi", "new_practice_medicare_enrollment"):
        what = str(p.get("taxonomy") or "").strip().lower()
        if what and len(what) <= 40:
            return what
    units = p.get("units_total")
    if (lead.signal_type or "") == "hud_new_owner" and isinstance(units, (int, float)) \
            and not isinstance(units, bool) and units > 0:
        return f"{int(units)} units"
    return _contact(lead)


def _industry(text: object) -> str:
    """A record's industry title, lowercased, when it is short enough to read
    in a line ("software publishers", "full-service restaurants"); "" else."""
    t = " ".join(str(text or "").split()).strip().lower()
    if not t or len(t) > 45 or t in ("all other", "other", "unclassified"):
        return ""
    return t.replace(" and ", " & ") if len(t) > 35 else t
