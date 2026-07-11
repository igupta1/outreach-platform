"""The commercial P&C insurance niche pack.

Buyer: a commercial property & casualty agent. Gift: companies that just hit a
growth / trigger moment (raised funding, registered a new business, pulled a
permit) — their coverage needs likely just changed. A softer, incumbent-locked
signal than trucking (most established firms already have a broker), so the copy
stays honest and times to the trigger; matching is geography-only (state-licensed
agents), reusing the engine's generalist path.

Leads come from the insurance pipeline's `pc-leads.json` (growth leads, no new
trucking carriers); `adapt_pc_lead` maps each row onto the outreach `Lead`.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from system_b import config
from system_b.clients.scraper_client import SnapshotScraper
from system_b.copy.lex import city_display, state_display
from system_b.gift.models import Gift, Prospect
from system_b.models import Lead, Signal
from system_b.niches.base import NichePack
from system_b.niches.text import noun

# Trigger -> honest plain-words line. Never a dollar amount on a raise (the
# copy honesty layer also strips figures as a backstop).
_TRIGGER_DESC: dict[str, str] = {
    "funding_raised": "just raised",
    "funding": "just raised",
    "new_business_filed": "just registered as a new business",
    "new_business": "just registered as a new business",
    "osha_inspection_recorded": "had a recent osha inspection",
    "building_permit_issued": "just pulled a building permit",
}
_DEFAULT_DESC = "just showed a growth signal"


# --- copy voice ------------------------------------------------------------

def _where(gift: Gift, prospect: Prospect) -> str:
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if gift.geo_level == "city" and city:
        return city
    if gift.geo_level == "state" and state:
        return state
    return ""


def _pc_subject(gift: Gift, prospect: Prospect) -> str:
    where = _where(gift, prospect)
    who = "a company" if gift.subject_shape == "singular" else "companies"
    if where:
        who = f"{who} in {where}"
    return f"{who} whose coverage needs probably just changed".lower()


def _pc_framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    where = _where(gift, prospect)
    companies = noun(n, "company", "companies")
    if where:
        return (
            f"saw you're based in {where}, so i pulled {n} {where} {companies} whose "
            f"insurance needs probably just changed:"
        )
    return f"i pulled {n} {companies} whose insurance needs probably just changed:"


def _pc_cta(gift: Gift, prospect: Prospect) -> str:
    where = _where(gift, prospect)
    if where:
        return f"want me to keep an eye out for {where} ones and send them your way?"
    return "want me to keep an eye out and send new ones your way?"


# 5b — left-field rotation, P&C-agent voice. Lowercase, no em dashes.
PC_LEFT_FIELD: tuple[str, ...] = (
    "most commercial agents i talk to say the best time to reach a business is "
    "right when something changes. built this to catch companies the week they raise or grow.",
    "every p&c agent i talk to says the same thing, you win on timing, not price. "
    "so i built a feed that flags companies right when their exposure changes.",
    "most agents i know wait for the renewal. built this to catch companies the "
    "moment a growth signal shows up, well before renewal season.",
    "the commercial agents i talk to say a fresh raise or a new entity is the "
    "opening. so i built a feed that surfaces exactly those.",
    "most agents i talk to say timing beats everything in commercial lines. built "
    "this to catch companies the week their coverage needs shift.",
)
PC_LEFT_FIELD_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")


def _pc_what_category(leads: list[Lead]) -> str:
    return "growth"


PC_PACK = NichePack(
    key="pc",
    signal_rank={t: 0 for t in _TRIGGER_DESC},
    priority_signal=None,
    raise_signals=frozenset({"funding_raised", "funding"}),   # raises -> templated, no $ figure
    what_category=_pc_what_category,
    subject=_pc_subject,
    framing=_pc_framing,
    cta=_pc_cta,
    left_field=PC_LEFT_FIELD,
    left_field_labels=PC_LEFT_FIELD_LABELS,
    funding_phrase=lambda lead: "just raised",                # never an amount
    priority_flag=None,
)


# --- inventory adapter (pc-leads.json -> outreach Lead) --------------------

_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def _freshness(event_date: str | None, today: date) -> str:
    if not event_date:
        return "stale"
    try:
        d = date.fromisoformat(event_date[:10])
    except (ValueError, TypeError):
        return "stale"
    delta = (today - d).days
    return "fresh" if 0 <= delta <= config.FRESH_WINDOW_DAYS else "stale"


def _top_signal(row: dict[str, Any]) -> dict[str, Any]:
    signals = row.get("signals") or []
    return signals[0] if signals else {}


def _trigger(row: dict[str, Any], sig: dict[str, Any]) -> str:
    return str(row.get("trigger_type") or sig.get("type") or "other")


def _lead_id(company: str, state: str | None, trigger: str) -> str:
    slug = _NONWORD_RE.sub("-", f"{company} {state or ''} {trigger}".lower()).strip("-")
    return f"pc:{slug}"


def adapt_pc_lead(row: dict[str, Any], *, today: date) -> Lead:
    """Map one insurance-pipeline P&C row onto the outreach `Lead` shape."""
    sig = _top_signal(row)
    trigger = _trigger(row, sig)
    event_date = (sig.get("captured_at") or "")[:10]
    company = row.get("name") or row.get("company") or ""
    state = row.get("state")
    city = row.get("city")
    desc = _TRIGGER_DESC.get(trigger, _DEFAULT_DESC)
    return Lead(
        id=_lead_id(company, state, trigger),
        company=company,
        domain=row.get("domain"),
        city=city,
        state=state,
        industry=row.get("industry"),
        niche=None,
        value_prop=row.get("insight"),
        signal_type=trigger,
        freshness=_freshness(event_date, today),
        signals=[
            Signal(
                type=trigger,
                date=event_date or None,
                date_confidence="high",
                plain_words_description=desc,
            )
        ],
    )


def load_pc_leads(path: str, *, today: date | None = None) -> list[Lead]:
    today = today or date.today()
    data = json.loads(Path(path).read_text())
    return [adapt_pc_lead(row, today=today) for row in (data.get("leads") or [])]


def pc_snapshot(path: str, *, today: date | None = None) -> SnapshotScraper:
    return SnapshotScraper(load_pc_leads(path, today=today), taxonomy={})


def pc_descriptions(leads: list[Lead]) -> dict[str, str]:
    out: dict[str, str] = {}
    for l in leads:
        desc = next(
            (s.plain_words_description for s in l.signals if s.plain_words_description),
            _DEFAULT_DESC,
        )
        out[l.id] = desc
    return out
