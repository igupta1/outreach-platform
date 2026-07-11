"""The commercial-trucking-insurance niche pack.

Buyer: a trucking-insurance agent. Gift: brand-new motor carriers (just granted
FMCSA operating authority) in the agent's territory — a carrier legally cannot
operate until its insurer files proof of coverage, and it's a new entity with no
incumbent agent, so it's the cleanest "must-buy-now" lead we have.

Matching is geography-only (agents are state-licensed), which the engine already
supports via the generalist path — so a trucking prospect is a `generalist` with
a `state` (and optionally `city`). There is no niche to detect on the lead side.

Leads come from the insurance pipeline's `trucking-leads.json` (a different JSON
shape than System A's /api/leads), so `adapt_trucking_lead` maps each row onto
the outreach `Lead` before the engine ever sees it.
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

_AUTHORITY_SIGNAL = "new_motor_carrier_authority"


# --- copy voice ------------------------------------------------------------

def _where(gift: Gift, prospect: Prospect) -> str:
    """The location word the gift's geo level lets us claim honestly ('' = none)."""
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if gift.geo_level == "city" and city:
        return city
    if gift.geo_level == "state" and state:
        return state
    return ""


def _trucking_subject(gift: Gift, prospect: Prospect) -> str:
    where = _where(gift, prospect)
    if gift.subject_shape == "singular":
        who = f"a new carrier in {where}" if where else "a new carrier"
        return f"{who} that just got its authority".lower()
    who = f"new carriers in {where}" if where else "new carriers"
    return f"{who} that just got their authority".lower()


def _trucking_framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    where = _where(gift, prospect)
    # Soft, location-honest opener: only claim a place when the leads are
    # actually there (geo_level), never overclaim the agent's book of business.
    if where:
        return (
            f"saw you're based in {where}, so i pulled {n} new {where} "
            f"carriers that just got their authority and need coverage:"
        )
    return (
        f"i pulled {n} new carriers that just got their authority and "
        f"need coverage:"
    )


def _trucking_cta(gift: Gift, prospect: Prospect) -> str:
    where = _where(gift, prospect)
    if where:
        return f"want me to keep an eye out for new {where} carriers and send them your way?"
    return "want me to keep an eye out for new carriers and send them your way?"


# 5b — left-field rotation, trucking-agent voice. House style: all lowercase,
# no em dashes, kept exactly as authored.
TRUCKING_LEFT_FIELD: tuple[str, ...] = (
    "most agents i talk to say new-authority trucking is all word of mouth, "
    "till it dries up. built this to catch carriers the day their authority goes active.",
    "every trucking agent i talk to says the same thing, the good new-authority "
    "leads go to whoever calls first. so i built a feed that catches carriers the "
    "day they register.",
    "most agents i know chase mc numbers off lists everyone else already has. "
    "built this to surface carriers the moment their authority goes active.",
    "the trucking agents i talk to say new authorities are the best leads and the "
    "hardest to time. so i built a feed that flags them the day they register.",
    "most agents i talk to say the first call wins a new authority. built this to "
    "catch carriers right when their authority goes active.",
)
TRUCKING_LEFT_FIELD_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")


def _trucking_what_category(leads: list[Lead]) -> str:
    return "new_authority"


TRUCKING_PACK = NichePack(
    key="trucking",
    signal_rank={_AUTHORITY_SIGNAL: 0},
    priority_signal=None,            # single signal, geo-matched — no lead-first special
    raise_signals=frozenset(),       # no raises → lead lines use the plain description
    what_category=_trucking_what_category,
    subject=_trucking_subject,
    framing=_trucking_framing,
    cta=_trucking_cta,
    left_field=TRUCKING_LEFT_FIELD,
    left_field_labels=TRUCKING_LEFT_FIELD_LABELS,
    funding_phrase=None,
    priority_flag=None,
)


# --- inventory adapter (insurance trucking-leads.json -> outreach Lead) -----

_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def _freshness(event_date: str, today: date) -> str:
    """fresh within FRESH_WINDOW_DAYS of the authority date, else stale."""
    try:
        d = date.fromisoformat((event_date or "")[:10])
    except (ValueError, TypeError):
        return "stale"
    delta = (today - d).days
    return "fresh" if 0 <= delta <= config.FRESH_WINDOW_DAYS else "stale"


def _authority_signal(row: dict[str, Any]) -> dict[str, Any]:
    signals = row.get("signals") or []
    for s in signals:
        if s.get("type") == _AUTHORITY_SIGNAL:
            return s
    return signals[0] if signals else {}


def _lead_id(usdot: Any, company: str, state: str | None) -> str:
    if usdot:
        return f"usdot:{usdot}"
    slug = _NONWORD_RE.sub("-", f"{company} {state or ''}".lower()).strip("-")
    return f"trucking:{slug}"


def _description(power_units: int | None) -> str:
    base = "just got their fmcsa operating authority"
    if power_units and power_units > 0:
        base += f", {power_units} truck" + ("s" if power_units != 1 else "")
    return base


def adapt_trucking_lead(row: dict[str, Any], *, today: date) -> Lead:
    """Map one insurance-pipeline trucking row onto the outreach `Lead` shape."""
    sig = _authority_signal(row)
    payload = sig.get("payload") or {}
    usdot = payload.get("usdot")
    event_date = payload.get("issue_date") or (sig.get("captured_at") or "")[:10]
    power = payload.get("fleet_size_power_units")
    company = row.get("name") or row.get("company") or ""
    state = row.get("state") or payload.get("state")
    city = row.get("city") or payload.get("city")
    return Lead(
        id=_lead_id(usdot, company, state),
        company=company,
        domain=row.get("domain"),
        city=city,
        state=state,
        industry="logistics_transport",
        niche="trucking_freight",
        value_prop=row.get("insight"),
        signal_type=_AUTHORITY_SIGNAL,
        freshness=_freshness(event_date, today),
        signals=[
            Signal(
                type=_AUTHORITY_SIGNAL,
                date=event_date or None,
                date_confidence="high",
                plain_words_description=_description(power),
            )
        ],
    )


def load_trucking_leads(path: str, *, today: date | None = None) -> list[Lead]:
    """Read the insurance pipeline's trucking-leads.json and adapt every row."""
    today = today or date.today()
    data = json.loads(Path(path).read_text())
    return [adapt_trucking_lead(row, today=today) for row in (data.get("leads") or [])]


def trucking_snapshot(path: str, *, today: date | None = None) -> SnapshotScraper:
    """A SnapshotScraper over the adapted trucking inventory (taxonomy unused —
    trucking matches on geography, not niche)."""
    return SnapshotScraper(load_trucking_leads(path, today=today), taxonomy={})


def trucking_descriptions(leads: list[Lead]) -> dict[str, str]:
    """Templated per-lead descriptions (no LLM needed — every trucking lead is
    the same 'new authority' signal). Keyed by lead id for build_email_1."""
    out: dict[str, str] = {}
    for l in leads:
        desc = next(
            (s.plain_words_description for s in l.signals if s.plain_words_description),
            "just got their fmcsa operating authority",
        )
        out[l.id] = desc
    return out
