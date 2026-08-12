"""Assemble the per-prospect review payload — everything the reviewer needs to
approve or edit ONE prospect's sequence, as a plain JSON-serializable dict.

It gathers what the pipeline already computed but the CSV throws away:
  * how we classified the niche (verbatim phrase + the URL it was found on),
  * every gift lead's evidence (signal type, plain-words line, date, domain, and
    the source_url link to the actual filing / job post / breach disclosure),
  * the honesty/review flags raised while drafting,
  * the editable copy (subject + the three email bodies).

Pure: no I/O, no network. `research` may be None (some callers/tests skip it);
the prospect object is authoritative for classification either way.
"""

from __future__ import annotations

from typing import Any

from system_b.copy.email import _client_names_phrase, is_job_posting, job_phrase
from system_b.copy.lex import niche_display, revenue_display
from system_b.copy.subject import niche_claim
from system_b.gift.models import Gift, Prospect

_HOW_WE_KNOW = {
    "site": "stated verbatim on their own site",
    "client_list": "named as clients on their own site",
}


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving de-dup — the same flag can come from several drafts."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _grounded(lead: Any) -> str:
    """The lead's own verbatim evidence line — what the templated copy is built
    from. Shown on the review card so the operator checks the source, not a
    paraphrase of it."""
    return next(
        (s.plain_words_description for s in lead.signals if s.plain_words_description),
        "",
    )


def _lead_entry(lead: Any) -> dict[str, Any]:
    """One evidence row: everything needed to CHECK the claim, nothing else.

    Reviewing asks one question — is this safe to send? — so this carries only
    what answers it: who the company is, what the copy claims about them, when
    it happened, and the link that proves it. The engine internals that used to
    ride along (match_level, freshness, date_confidence, best, used_in,
    domainless, value_prop) never changed a reviewer's decision, and
    `description` duplicated the copy verbatim two inches further down."""
    return {
        "company": lead.company,
        "role": _role(lead),
        "date": (lead.newest_date or "")[:10] or None,
        "source_url": lead.primary_source_url,
    }


def _role(lead: Any) -> str:
    """What the copy claims, in the copy's own words — so the review can never
    contradict the sent email."""
    if is_job_posting(lead):
        return job_phrase(lead)
    return _grounded(lead).strip()


# How personal the email actually reads, strongest first. Two different things
# make an email personal and the tiers rank them together: EVIDENCE that we read
# their site (a stated niche, named clients, a revenue range — none of which can
# be faked from an Apollo export) and MATCH quality (whether the gift is on their
# vertical or merely near them). The top tiers have both.
#
# Derived from the SAME gates the copy uses, never from the data alone: a
# prospect can carry a revenue range that the opener does not use (client-list
# openers skip it), and `niche_claim` can decline a vertical the prospect object
# still has. Reading the data instead of the gates would sort emails by what we
# know rather than by what we said.
_PERSONALIZATION_TIERS = (
    (1, "niche + named clients"),
    (2, "niche + revenue"),
    (3, "niche"),
    (4, "revenue + city"),
    (5, "revenue"),
    (6, "city"),
    (7, "state"),
    (8, "none"),
)


def _personalization(prospect: Prospect, gift: Gift) -> dict[str, Any]:
    """{rank, label} for sorting the review gate — and therefore the exported
    CSV — most-personalized first."""
    niche = niche_claim(gift, prospect)
    named = bool(_client_names_phrase(prospect))
    # Mirrors `copy.email._framing`: a client-list opener already names two real
    # clients, so it never spends words on a revenue range.
    revenue = bool(prospect.client_revenue) and prospect.niche_source != "client_list"
    geo = gift.geo_level

    if niche and named:
        rank = 1
    elif niche and revenue:
        rank = 2
    elif niche:
        rank = 3
    elif revenue and geo == "city":
        rank = 4
    elif revenue:
        rank = 5
    elif geo == "city":
        rank = 6
    elif geo == "state":
        rank = 7
    else:
        rank = 8
    return {"rank": rank, "label": dict(_PERSONALIZATION_TIERS)[rank]}


def build_review(
    prospect: Prospect,
    gift: Gift,
    research: Any,
    email1: Any,
    followups: list[Any],
    followup_leads: list[Any],
    row: dict[str, Any],
    dms: dict[str, str] | None = None,
) -> dict[str, Any]:
    """One prospect's review card as a plain dict.

    Every lead shows its own grounded plain-words line — the same evidence the
    templated copy is built from. `followup_leads` is aligned to steps 2 and 3
    (either entry may be None when the well ran dry).
    """
    mp = prospect.match_param
    niche = niche_display(mp) if mp else None
    if prospect.classification == "niched":
        how = _HOW_WE_KNOW.get(prospect.niche_source, "classified from their site")
    else:
        how = "generalist — no vertical claimed (leads matched on geography)"

    evidence = []
    research_flags: list[str] = []
    if research is not None:
        evidence = [
            {"kind": e.kind, "text": e.text, "url": e.url}
            for e in (getattr(research, "evidence", None) or [])
        ]
        research_flags = list(getattr(research, "flags", None) or [])

    flags = _dedupe(
        research_flags
        + list(getattr(email1, "flags", None) or [])
        + [f for d in followups for f in (getattr(d, "flags", None) or [])]
    )

    leads = [_lead_entry(lead) for lead in gift.leads]
    for lead in followup_leads:
        if lead is not None:
            leads.append(_lead_entry(lead))

    return {
        # identity (drives the header + the exported CSV)
        "company": prospect.firm_name,
        "first_name": prospect.first_name or "",
        "last_name": row.get("last_name") or "",
        "email": (row.get("email") or "").strip(),
        "city": prospect.city,
        "state": prospect.state,
        "linkedin": row.get("linkedin") or "",
        # classification / how we know
        "classification": prospect.classification,
        "match_param": f"{mp[0]}={mp[1]}" if mp else None,
        "niche": niche,
        "niche_phrase": prospect.niche_phrase,
        "niche_source": prospect.niche_source,
        "niche_exclusivity": prospect.niche_exclusivity,
        "how_we_know": how,
        "geo_level": gift.geo_level,
        # Drives the review gate's sort order, which is also the CSV's row order.
        "personalization": _personalization(prospect, gift),
        # The two extra levers, rendered exactly as the copy renders them, so the
        # card shows what was actually said rather than the raw parsed values.
        "named_clients": list(prospect.client_names or []),
        "revenue": revenue_display(prospect.client_revenue),
        "left_field_variant": getattr(email1, "left_field_variant", ""),
        # evidence
        "evidence": evidence,
        "flags": flags,
        "leads": leads,
        # editable copy (these four are the only editable fields on the page)
        "subject": getattr(email1, "subject", ""),
        "email_1": getattr(email1, "body", ""),
        "email_2": getattr(followups[0], "body", "") if followups else "",
        "email_3": getattr(followups[1], "body", "") if len(followups) > 1 else "",
        # The LinkedIn half, editable on the same card: one review pass covers
        # both channels, and an edit here reaches the exported CSV.
        "li_dm_1": (dms or {}).get("li_dm_1", ""),
        "li_dm_1_evergreen": (dms or {}).get("li_dm_1_evergreen", ""),
        "li_dm_2": (dms or {}).get("li_dm_2", ""),
    }
