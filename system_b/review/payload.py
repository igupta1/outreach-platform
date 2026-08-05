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

from system_b.copy.email import is_job_posting, job_phrase
from system_b.copy.lex import niche_display
from system_b.gift.engine import compute_match_level
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


def _signal_evidence(lead: Any) -> list[dict[str, Any]]:
    """Every signal on the lead, as evidence rows (the verbatim line + link)."""
    return [
        {
            "type": s.type,
            "date": s.date,
            "evidence_text": s.plain_words_description,
            "source_url": s.source_url,
        }
        for s in lead.signals
    ]


def _grounded(lead: Any) -> str:
    """The lead's own verbatim evidence line — what the templated copy is built
    from. Shown on the review card so the operator checks the source, not a
    paraphrase of it."""
    return next(
        (s.plain_words_description for s in lead.signals if s.plain_words_description),
        "",
    )


def _lead_entry(
    lead: Any, prospect: Prospect, best_id: str | None, *,
    used_in: str, description: str,
) -> dict[str, Any]:
    # Show the SAME line the email uses for a job posting (deterministic "is
    # looking for a {role}"), not the raw LLM clause — so the review never
    # contradicts the sent copy.
    if is_job_posting(lead):
        description = job_phrase(lead)
    return {
        "company": lead.company,
        "used_in": used_in,
        "best": best_id is not None and lead.id == best_id,
        "signal_type": lead.signal_type,
        "match_level": compute_match_level(lead, prospect),
        "freshness": lead.freshness,
        "date": lead.newest_date or None,
        "date_confidence": lead.effective_date_confidence,
        "domain": lead.domain,
        "domainless": lead.domain is None,
        "city": lead.city,
        "state": lead.state,
        "value_prop": lead.value_prop,
        "description": (description or "").strip(),   # the plain-words line used in the copy
        "source_url": lead.primary_source_url,         # headline evidence link
        "signals": _signal_evidence(lead),             # all evidence rows
    }


def build_review(
    prospect: Prospect,
    gift: Gift,
    research: Any,
    email1: Any,
    followups: list[Any],
    followup_leads: list[Any],
    row: dict[str, Any],
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

    leads = [
        _lead_entry(
            lead, prospect, gift.best_lead.id,
            used_in="email 1", description=_grounded(lead),
        )
        for lead in gift.leads
    ]
    for step, lead in zip((2, 3), followup_leads):
        if lead is not None:
            desc = next(
                (s.plain_words_description for s in lead.signals if s.plain_words_description),
                "",
            )
            leads.append(
                _lead_entry(lead, prospect, None, used_in=f"email {step}", description=desc)
            )

    return {
        # identity (drives the header + the exported CSV)
        "company": prospect.firm_name,
        "first_name": prospect.first_name or "",
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
    }
