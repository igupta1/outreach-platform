"""The bookkeeping / outsourced-accounting niche pack.

Buyer: a bookkeeping or outsourced-accounting firm. Gift: small companies in the
firm's area that just posted a *junior* finance role (bookkeeper, staff
accountant, AP/AR clerk) — a company with an accounting need that hasn't
committed to an in-house finance department yet, i.e. the outsource window.

Like trucking, matching is geography-only (bookkeeping firms serve local small
businesses), so a prospect is a `generalist` with a `city`/`state` and the
engine's existing generalist path does the work — no site research needed.

Leads come from the cfo pipeline's `bookkeeping-leads.json` (junior finance
hires, `role_tier=junior`); `adapt_bookkeeping_lead` maps each row onto the
outreach `Lead` before the engine sees it.
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

_BOOKKEEPING_SIGNAL = "job_posted_bookkeeping"


# --- copy voice ------------------------------------------------------------

def _where(gift: Gift, prospect: Prospect) -> str:
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if gift.geo_level == "city" and city:
        return city
    if gift.geo_level == "state" and state:
        return state
    return ""


def _bookkeeping_subject(gift: Gift, prospect: Prospect) -> str:
    where = _where(gift, prospect)
    if gift.subject_shape == "singular":
        who = f"a company in {where}" if where else "a company"
        return f"{who} that just posted a bookkeeping role".lower()
    who = f"companies in {where}" if where else "companies"
    return f"{who} hiring junior finance right now".lower()


def _bookkeeping_framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    where = _where(gift, prospect)
    if where:
        return (
            f"saw you're based in {where}, so i pulled {n} {where} companies that "
            f"just posted a junior finance role and could use bookkeeping help:"
        )
    return (
        f"i pulled {n} companies that just posted a junior finance role and "
        f"could use bookkeeping help:"
    )


def _bookkeeping_cta(gift: Gift, prospect: Prospect) -> str:
    where = _where(gift, prospect)
    if where:
        return f"want me to keep an eye out for {where} ones and send them your way?"
    return "want me to keep an eye out and send new ones your way?"


# 5b — left-field rotation, bookkeeping-firm voice. Lowercase, no em dashes.
BOOKKEEPING_LEFT_FIELD: tuple[str, ...] = (
    "most bookkeepers i talk to say clients come by referral, till it slows down. "
    "built this to catch companies the week they start hiring finance help.",
    "every bookkeeper i talk to says the same thing, the best clients are the ones "
    "who just realized they need help. so i built a feed that catches them the day "
    "they post a finance role.",
    "most accounting firms i know wait for the referral. built this to surface "
    "companies the moment they post their first finance hire.",
    "the bookkeepers i talk to say the hire-vs-outsource moment is the whole game. "
    "so i built a feed that flags companies right when they post a junior finance role.",
    "most bookkeepers i talk to say timing is everything. built this to catch "
    "companies the week a finance-need signal shows up.",
)
BOOKKEEPING_LEFT_FIELD_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")


def _bookkeeping_what_category(leads: list[Lead]) -> str:
    return "junior_finance"


BOOKKEEPING_PACK = NichePack(
    key="bookkeeping",
    signal_rank={_BOOKKEEPING_SIGNAL: 0},
    priority_signal=None,            # single signal, geo-matched
    raise_signals=frozenset(),       # no raises → lead lines use the plain description
    what_category=_bookkeeping_what_category,
    subject=_bookkeeping_subject,
    framing=_bookkeeping_framing,
    cta=_bookkeeping_cta,
    left_field=BOOKKEEPING_LEFT_FIELD,
    left_field_labels=BOOKKEEPING_LEFT_FIELD_LABELS,
    funding_phrase=None,
    priority_flag=None,
)


# --- inventory adapter (bookkeeping-leads.json -> outreach Lead) ------------

_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def _freshness(event_date: str, today: date) -> str:
    try:
        d = date.fromisoformat((event_date or "")[:10])
    except (ValueError, TypeError):
        return "stale"
    delta = (today - d).days
    return "fresh" if 0 <= delta <= config.FRESH_WINDOW_DAYS else "stale"


def _signal(row: dict[str, Any]) -> dict[str, Any]:
    signals = row.get("signals") or []
    for s in signals:
        if s.get("type") == _BOOKKEEPING_SIGNAL:
            return s
    return signals[0] if signals else {}


def _lead_id(company: str, state: str | None, title: str) -> str:
    slug = _NONWORD_RE.sub("-", f"{company} {state or ''} {title}".lower()).strip("-")
    return f"bookkeeping:{slug}"


def adapt_bookkeeping_lead(row: dict[str, Any], *, today: date) -> Lead:
    """Map one cfo-pipeline bookkeeping row onto the outreach `Lead` shape."""
    sig = _signal(row)
    payload = sig.get("payload") or {}
    title = str(payload.get("title") or "").strip()
    event_date = payload.get("date_posted") or (sig.get("captured_at") or "")[:10]
    company = row.get("name") or row.get("company") or ""
    state = row.get("state") or payload.get("state")
    city = row.get("city") or payload.get("city")
    desc = f"just posted a {title.lower()} role" if title else "just posted a junior finance role"
    return Lead(
        id=_lead_id(company, state, title),
        company=company,
        domain=row.get("domain"),
        city=city,
        state=state,
        industry=None,
        niche=None,
        value_prop=row.get("insight"),
        signal_type=_BOOKKEEPING_SIGNAL,
        freshness=_freshness(event_date, today),
        signals=[
            Signal(
                type=_BOOKKEEPING_SIGNAL,
                date=event_date or None,
                date_confidence="high",
                plain_words_description=desc,
            )
        ],
    )


def load_bookkeeping_leads(path: str, *, today: date | None = None) -> list[Lead]:
    today = today or date.today()
    data = json.loads(Path(path).read_text())
    return [adapt_bookkeeping_lead(row, today=today) for row in (data.get("leads") or [])]


def bookkeeping_snapshot(path: str, *, today: date | None = None) -> SnapshotScraper:
    return SnapshotScraper(load_bookkeeping_leads(path, today=today), taxonomy={})


def bookkeeping_descriptions(leads: list[Lead]) -> dict[str, str]:
    out: dict[str, str] = {}
    for l in leads:
        desc = next(
            (s.plain_words_description for s in l.signals if s.plain_words_description),
            "just posted a junior finance role",
        )
        out[l.id] = desc
    return out
