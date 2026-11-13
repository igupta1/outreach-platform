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
from datetime import date

from system_b.models import Lead

# Roles worth printing beside a name, as the reader would say them. A
# source's own wording is mapped to a plain role ("Signed the Form 5500 as plan
# administrator" -> "plan administrator", "AMBR" -> "authorized member");
# anything unknown prints no name. 2026-11-11: widened from 30 titles, which
# kept 1 in 3 of the named people on the record.
_ROLES = (
    (r"owner|co-owner|sole owner", None),
    (r"founder|co-founder", None),
    (r"ceo|chief executive officer|president(?: ?[&/] ?ceo)?|ceo ?[&/] ?president", None),
    (r"coo|chief operating officer", None),
    (r"vice president|executive vice president|evp|svp|vp", "vice president"),
    (r"executive director|interim executive director", None),
    (r"director|managing director|executive officer", None),
    (r"officer,? ?(?:and |& |/ ?)?director|director,? ?(?:and |& |/ ?)?officer", "director"),
    (r"managing member|member|sole member|authorized member|ambr|mbr|mgrm", None),
    (r"managing partner|partner|general partner", None),
    (r"principal|principal investigator", None),
    (r"general manager|manager|mgr|office manager|business manager", None),
    (r"administrator|plan administrator|signed the form 5500 as plan administrator",
     "plan administrator"),
    (r"officer|chair|chairman|chairperson|chairwoman|secretary|trustee|permittee", None),
    (r"certified [a-z ]+ contractor|qualifier|qualifying individual", "license holder"),
    (r"authorized official|contact person on form [\w-]+|contact named on form [\w-]+",
     "contact"),
)
_ROLE_RES = [(re.compile(rf"^(?:{pat})$", re.I), word) for pat, word in _ROLES]
_ROLE_WORDS = {"mgr": "manager", "ambr": "authorized member", "mbr": "member",
               "mgrm": "managing member", "administrator": "administrator",
               "vp": "vice president"}
# A lead whose named contact is its own CFO reads as one that already has
# finance help (2026-11-05): never printed.
_FINANCE_ROLE_RE = re.compile(r"\b(?:cfo|controller|treasurer|finance|financial|accounting)\b", re.I)
# Legal endings, so "Shabbat Angels" is seen to be the org's own name.
_LEGAL_END_RE = re.compile(r"[,.]?\s+(?:llc|l\.l\.c\.|inc|inc\.|corp|corporation|co|ltd|pllc|pc|lp|llp)\.?$", re.I)


def role_word(title: str | None) -> str:
    """The plain role for a source's title, or "" when it is not one we print."""
    t = " ".join((title or "").split()).strip(" .,")
    if not t or _FINANCE_ROLE_RE.search(t):
        return ""
    for rx, word in _ROLE_RES:
        if rx.match(t):
            return word or _ROLE_WORDS.get(t.lower(), t.lower())
    return ""


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


# The names a finance reader knows on sight (2026-11-06: "transportation
# dept" 54 times and "securities and exchange commission" read as jargon).
# An agency missing here prints nothing: the dollar figure carries the line.
_AGENCY_SHORT = {
    "national science foundation": "nsf",
    "national institutes of health": "nih",
    "department of health and human services": "hhs",
    "department of agriculture": "usda",
    "department of the interior": "interior",
    "department of transportation": "dot",
    "department of commerce": "commerce",
    "department of veterans affairs": "va",
    "department of justice": "doj",
    "department of homeland security": "dhs",
    "department of energy": "doe",
    "department of education": "education",
    "department of the treasury": "treasury",
    "department of state": "state dept",
    "department of labor": "labor",
    "department of defense": "defense",
    "department of the army": "army",
    "department of the air force": "air force",
    "department of the navy": "navy",
    "defense logistics agency": "defense",
    "national aeronautics and space administration": "nasa",
    "general services administration": "gsa",
    "environmental protection agency": "epa",
    "securities and exchange commission": "sec",
    "federal trade commission": "ftc",
    "social security administration": "ssa",
    "small business administration": "sba",
}


def agency(p: dict) -> str:
    branch = str(p.get("branch") or "")
    if "National Institutes of Health" in branch:
        return "nih"
    top = str(p.get("awarding_agency") or p.get("agency") or "").strip()
    sub = str(p.get("awarding_sub_agency") or "").strip()
    name = sub if top.lower() == "department of defense" and sub else top
    name = re.sub(r"^u\.?s\.?\s+", "", name, flags=re.I).lower()
    return _AGENCY_SHORT.get(name) or (_AGENCY_SHORT.get(top.lower(), "") if sub else "")


def _payload(lead: Lead) -> dict:
    out: dict = {}
    for s in lead.signals or []:
        out.update(s.payload or {})
    return out


def _person(lead: Lead) -> tuple[str, str] | None:
    """(name, plain role) of the record's named contact, or None. Single-letter
    initials are dropped ("Douglas K Bardin" -> "Douglas Bardin"); a "contact"
    that is the organization's own name is not a person."""
    name = " ".join((lead.contact_name or "").split())
    role = role_word(lead.contact_title)
    if not name or not role:
        return None
    if name.isupper() or name.islower():
        name = name.title()
    # "plan administrator" comes from a Form 5500: beside an SBA loan it reads
    # as the wrong person (2026-11-13). Only on a benefit-plan lead.
    if role == "plan administrator" and not (lead.signal_type or "").startswith(
            ("plan_", "welfare_", "pension_")):
        return None
    org = _LEGAL_END_RE.sub("", " ".join((lead.company or "").split())).lower()
    name = _first_last(name)
    if len(name.split()) < 2 or name.lower() == org:
        return None
    return name, role


_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "rev", "hon"}   # "Sherrilyn Ms" (2026-11-12)
_PARTICLES = {"de", "del", "della", "da", "di", "du", "la", "le", "van", "von", "der", "st"}


def _first_last(name: str) -> str:
    """First and last name only (2026-11-12, the user: no middle names):
    "Edward Alex Polevoy" -> "Edward Polevoy", "Douglas K Bardin" -> "Douglas
    Bardin". A surname particle stays ("Maria de la Cruz"), a suffix goes."""
    words = [w for w in name.split() if (len(w.rstrip(".,")) > 1 or w.lower() in _PARTICLES)
             and w.lower().strip(".,") not in _TITLES]
    while len(words) > 2 and words[-1].lower().strip(".,") in _SUFFIXES:
        words.pop()
    if len(words) <= 2:
        return " ".join(words)
    last = [words[-1]]
    for w in reversed(words[1:-1]):
        if w.lower() not in _PARTICLES:
            break
        last.insert(0, w)
    return " ".join([words[0], *last])


def _contact(lead: Lead) -> str:
    who = _person(lead)
    return f"{who[0]}, {who[1]}" if who else ""


def contact(lead: Lead) -> str:
    """The named person on the record, role first: "principal Edward Alex
    Polevoy" (2026-11-11, the user: "include the contact name when we can").
    A name the reader can ask for turns a company into a lead they can act on.
    "" when the record names no usable person."""
    who = _person(lead)
    if not who:
        return ""
    return f"{_ROLE_WORDS_BEFORE.get(who[1], who[1])} {who[0]}"


# Roles that read oddly before a name.
_ROLE_WORDS_BEFORE = {"authorized official": "contact"}

# The record's own date says the news is new (2026-11-11, the user: "sound as
# fresh as possible without doing too much"): "oct 23" when the event is at
# most FRESH_DAYS old, nothing otherwise (an old date only says "stale").
# Only for types whose record date IS the news (a licence issued, a loan
# approved, an award signed, an owner changed, a lien filed). Never for a
# filing about a standing situation: "Rising Point Capital (4 funds, oct 15)"
# would say the funds are new when only the form is, and a 990's or a 5500's
# year end is not when anything happened.
FRESH_DAYS = 30
_NEWS_DATED = re.compile(
    r"new|first|licen[cs]e|permit|registration|award|contract|loan|sba|owner|began|"
    r"clearance|credit_allocated|credit_approved|certified|placed_in_service|subaward|"
    r"lien|forfeited|revoked|suspended|stop_work|upgrade")
_PERIOD_DATED = ("plan_", "welfare_", "pension_", "nonprofit_", "adv_")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def fresh_date(lead: Lead, today: date) -> str:
    t = lead.signal_type or ""
    if t.startswith(_PERIOD_DATED) or not _NEWS_DATED.search(t) \
            or lead.effective_date_confidence != "high":
        return ""
    iso = (lead.headline_signal.date if lead.headline_signal else None) or lead.newest_date
    try:
        when = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return ""
    if not 0 <= (today - when).days <= FRESH_DAYS:
        return ""
    return f"{_MONTHS[when.month - 1]} {when.day}"


def record_fact(lead: Lead, *, with_contact: bool = True) -> str:
    p = _payload(lead)
    award = money(p.get("award_amount"))
    if award:
        # 2026-11-12: the figure alone; the agency ("va") was a third detail.
        return award
    loan = money(p.get("loan_amount"))
    if loan:
        # 2026-11-12: the amount alone; the borrower's NAICS title ("offices of
        # dentists") repeated what the opener already says.
        return f"{loan} loan"
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
    return _contact(lead) if with_contact else ""


def _industry(text: object) -> str:
    """A record's industry title, lowercased, when it is short enough to read
    in a line ("software publishers", "full-service restaurants"); "" else.
    A bare code ("naics 722511", 2026-11-12) is looked up, never printed."""
    t = " ".join(str(text or "").split()).strip().lower()
    code = re.fullmatch(r"(?:naics\s*)?(\d{2,6})", t)
    if code:
        from system_b.gift.fit import naics_title

        t = " ".join(str(naics_title(code.group(1)) or "").split()).strip().lower()
    if not t or len(t) > 45 or t in ("all other", "other", "unclassified"):
        return ""
    return t.replace(" and ", " & ") if len(t) > 35 else t
