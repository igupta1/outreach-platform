"""The recruiter / staffing-agency niche pack.

Buyer: a recruiting agency. Gift: companies hiring heavily (3+ unique roles in
30 days) — the loudest, least-ambiguous "needs hiring help" signal there is.

Recruiters specialize by *function* (a finance recruiter, a sales recruiter, a
tech recruiter), so the match is on function with a geography fallback:
  - a recruiter with a stated function  -> heavy hirers whose primary function
    matches (niched path); if none nearby, the engine falls back to geo and the
    honesty gate drops the function claim (copy becomes a plain geo email).
  - a generalist recruiter               -> heavy hirers in their area.

The trick that makes this a pure engine reuse: the adapter maps each company's
`primary_function` onto the lead's `niche`, so the engine's existing niche+geo
match levels ARE the recruiter routing. Leads come from the recruiter pipeline's
`recruiter-leads.json`.
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

_HIRING_SIGNAL = "hiring_volume"


# --- copy voice ------------------------------------------------------------

def _where(gift: Gift, prospect: Prospect) -> str:
    city = city_display(prospect.city)
    state = state_display(prospect.state)
    if gift.geo_level == "city" and city:
        return city
    if gift.geo_level == "state" and state:
        return state
    return ""


def _function_word(gift: Gift, prospect: Prospect) -> str | None:
    """The recruiter's function, claimable only when the gift is all on-function
    (gift.all_niche) — otherwise the engine fell back to geo and we must not
    claim it (honesty gate)."""
    if gift.all_niche and prospect.match_param and prospect.match_param[0] == "niche":
        return prospect.match_param[1].replace("_", " ")
    return None


def _recruiter_subject(gift: Gift, prospect: Prospect) -> str:
    func = _function_word(gift, prospect)
    where = _where(gift, prospect)
    who = "a company" if gift.subject_shape == "singular" else "companies"
    if where:
        who = f"{who} in {where}"
    what = f"hiring {func} right now" if func else "hiring heavily right now"
    return f"{who} {what}".lower()


def _recruiter_framing(gift: Gift, prospect: Prospect) -> str:
    n = gift.gift_size
    func = _function_word(gift, prospect)
    where = _where(gift, prospect)
    companies = noun(n, "company", "companies")
    if func and where:
        return f"saw you recruit {func}, so i pulled {n} {where} {companies} hiring {func} heavily right now:"
    if func:
        return f"saw you recruit {func}, so i pulled {n} {companies} hiring {func} heavily right now:"
    if where:
        return f"saw you're based in {where}, so i pulled {n} {where} {companies} hiring heavily right now:"
    return f"i pulled {n} {companies} hiring heavily right now:"


def _recruiter_cta(gift: Gift, prospect: Prospect) -> str:
    func = _function_word(gift, prospect)
    where = _where(gift, prospect)
    if func:
        return f"want me to keep an eye out for companies hiring {func} and send them your way?"
    if where:
        return f"want me to keep an eye out for {where} ones and send them your way?"
    return "want me to keep an eye out and send new ones your way?"


# 5b — left-field rotation, recruiter/staffing voice. Lowercase, no em dashes.
RECRUITER_LEFT_FIELD: tuple[str, ...] = (
    "most recruiters i talk to say the best req is the one nobody else has found "
    "yet. built this to catch companies the week they start hiring in volume.",
    "every recruiter i talk to says the same thing, timing the req is half the "
    "placement. so i built a feed that flags companies the moment they post a burst of roles.",
    "most agencies i know work the same job boards everyone else does. built this "
    "to surface companies right when their open-role count spikes.",
    "the recruiters i talk to say a company hiring 3+ roles at once is the whole "
    "ballgame. so i built a feed that catches exactly that.",
    "most recruiters i talk to say the first call on a hiring spike wins the "
    "contract. built this to catch companies the week the spike shows up.",
)
RECRUITER_LEFT_FIELD_LABELS: tuple[str, ...] = ("A", "B", "C", "D", "E")


def _recruiter_what_category(leads: list[Lead]) -> str:
    return "hiring"


RECRUITER_PACK = NichePack(
    key="recruiter",
    signal_rank={_HIRING_SIGNAL: 0},
    priority_signal=None,
    raise_signals=frozenset(),
    what_category=_recruiter_what_category,
    subject=_recruiter_subject,
    framing=_recruiter_framing,
    cta=_recruiter_cta,
    left_field=RECRUITER_LEFT_FIELD,
    left_field_labels=RECRUITER_LEFT_FIELD_LABELS,
    funding_phrase=None,
    priority_flag=None,
)


# --- inventory adapter (recruiter-leads.json -> outreach Lead) --------------

_NONWORD_RE = re.compile(r"[^a-z0-9]+")


def _freshness(event_date: str | None, today: date) -> str:
    if not event_date:
        return "fresh"                       # undated hiring-volume rows are current
    try:
        d = date.fromisoformat(event_date[:10])
    except (ValueError, TypeError):
        return "fresh"
    delta = (today - d).days
    return "fresh" if 0 <= delta <= config.FRESH_WINDOW_DAYS else "stale"


def _signal(row: dict[str, Any]) -> dict[str, Any]:
    signals = row.get("signals") or []
    for s in signals:
        if s.get("type") == _HIRING_SIGNAL:
            return s
    return signals[0] if signals else {}


def _lead_id(company: str, state: str | None) -> str:
    slug = _NONWORD_RE.sub("-", f"{company} {state or ''}".lower()).strip("-")
    return f"recruiter:{slug}"


def adapt_recruiter_lead(row: dict[str, Any], *, today: date) -> Lead:
    """Map one recruiter-pipeline row onto the outreach `Lead`. `primary_function`
    becomes the lead's `niche` so the engine's niche match = function match."""
    sig = _signal(row)
    payload = sig.get("payload") or {}
    func = row.get("primary_function") or payload.get("primary_function") or "other"
    count = row.get("unique_role_count") or payload.get("unique_role_count") or 0
    event_date = payload.get("date") or (sig.get("captured_at") or "")[:10]
    company = row.get("name") or row.get("company") or ""
    state = row.get("state")
    city = row.get("city")
    desc = f"posted {count} roles this month" if count else "hiring in volume this month"
    return Lead(
        id=_lead_id(company, state),
        company=company,
        domain=row.get("domain"),
        city=city,
        state=state,
        industry=func,
        niche=func,
        value_prop=row.get("insight"),
        signal_type=_HIRING_SIGNAL,
        freshness=_freshness(event_date, today),
        signals=[
            Signal(
                type=_HIRING_SIGNAL,
                date=event_date or None,
                date_confidence="high",
                plain_words_description=desc,
            )
        ],
    )


def load_recruiter_leads(path: str, *, today: date | None = None) -> list[Lead]:
    today = today or date.today()
    data = json.loads(Path(path).read_text())
    return [adapt_recruiter_lead(row, today=today) for row in (data.get("leads") or [])]


def recruiter_snapshot(path: str, *, today: date | None = None) -> SnapshotScraper:
    return SnapshotScraper(load_recruiter_leads(path, today=today), taxonomy={})


def recruiter_descriptions(leads: list[Lead]) -> dict[str, str]:
    out: dict[str, str] = {}
    for l in leads:
        desc = next(
            (s.plain_words_description for s in l.signals if s.plain_words_description),
            "hiring in volume this month",
        )
        out[l.id] = desc
    return out


# Recruiter self-description → function they place for. Ordered like the
# lead-side classifier (narrow before broad) so "security" wins over "engineering".
_SPECIALTY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("security", ("security recruit", "cybersecurity", "infosec", "security talent")),
    ("data", ("data science", "data recruit", "analytics talent", "machine learning talent")),
    ("finance", ("finance recruit", "accounting recruit", "finance talent", "fp&a", "controller", "cfo search")),
    ("sales", ("sales recruit", "sales talent", "gtm talent", "revenue talent", "account executive")),
    ("marketing", ("marketing recruit", "growth talent", "marketing talent")),
    ("product", ("product recruit", "product talent", "product management search")),
    ("design", ("design recruit", "design talent", "ux talent")),
    ("engineering", ("tech recruit", "technical recruit", "software talent", "engineering talent",
                     "developer", "swe", "it staffing")),
)


def detect_function(text: str | None) -> str | None:
    """Keyword-detect a recruiter's specialty function from site/description
    text; None when nothing specific appears (→ generalist)."""
    t = (text or "").lower()
    for func, kws in _SPECIALTY_KEYWORDS:
        if any(k in t for k in kws):
            return func
    return None


def detect_function_from_site(url: str, *, fetch=None) -> str | None:
    """Fetch the agency's site and detect its specialty function; None (→
    generalist) on any failure. `fetch` is injectable for tests."""
    if fetch is None:
        from system_b.research.fetcher import fetch_site as fetch
    try:
        site = fetch(url)
    except Exception:
        return None
    return detect_function(" ".join(site.values()))


def recruiter_prospect(
    firm_name: str, *, city: str | None = None, state: str | None = None,
    function: str | None = None, first_name: str | None = None,
) -> Prospect:
    """A recruiter prospect. With a `function` it's niched (function match + geo
    fallback); without, it's a generalist geo match."""
    func = (function or "").strip().lower().replace(" ", "_") or None
    return Prospect(
        firm_name=firm_name,
        city=city or None,
        state=state or None,
        classification="niched" if func else "generalist",
        match_param=("niche", func) if func else None,
        first_name=(first_name or "there"),
    )
