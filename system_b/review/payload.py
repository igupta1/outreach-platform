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
from system_b.copy.lex import niche_display, niche_noun, revenue_display
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


def _evidence_url(research: Any, kind: str, text: str | None = None) -> str:
    """The page a piece of evidence was found on: the row matching `text` when
    given, else the first row of that kind. "" when there is none."""
    rows = list(getattr(research, "evidence", None) or [])
    if text:
        for e in rows:
            if e.kind == kind and e.text == text:
                return e.url or ""
    for e in rows:
        if e.kind == kind:
            return e.url or ""
    return ""


def _claims(prospect: Prospect, gift: Gift, research: Any, body: str) -> list[dict[str, Any]]:
    """Every claim the copy makes ABOUT THE PROSPECT, keyed by the exact
    substring it appears as, so the gate can underline the words themselves and
    show what backs them on hover.

    This replaces reading a list at the bottom of the card and matching it up by
    eye. The evidence was always there; it was just not attached to the sentence
    that depends on it.

    Only claims whose text is really IN the rendered copy survive — the same
    verbatim discipline the rest of the pipeline uses. A claim the copy did not
    end up making must not be highlighted, and a template change that renames a
    phrase silently highlights nothing rather than pointing at the wrong words.

    `city`/`state` deliberately carry no URL and say so: they come from the
    Apollo export, not from the prospect's own site, which makes them the one
    claim on the card nobody verified."""
    mp = prospect.match_param
    niche = niche_claim(gift, prospect) if mp else None
    out: list[dict[str, Any]] = []

    if niche:
        kind = "client" if prospect.niche_source == "client_list" else "phrase"
        out.append({
            "text": niche_noun(niche),
            "label": "vertical",
            "quote": prospect.niche_phrase or "",
            "how": _HOW_WE_KNOW.get(prospect.niche_source, "classified from their site"),
            "url": _evidence_url(research, kind, prospect.niche_phrase),
        })

    named = _client_names_phrase(prospect)
    if named:
        rows = [e for e in (getattr(research, "evidence", None) or []) if e.kind == "client"]
        out.append({
            "text": named,
            "label": "clients",
            "quote": "  ·  ".join(e.text for e in rows[:6]),
            "how": "found on a page that presents them as clients",
            "url": rows[0].url if rows else "",
        })

    rev = revenue_display(getattr(prospect, "client_revenue", None))
    if rev:
        phrase = getattr(research, "revenue_phrase", None) or ""
        out.append({
            "text": rev,
            "label": "client revenue",
            "quote": phrase,
            "how": "stated verbatim on their own site",
            "url": _evidence_url(research, "revenue", phrase),
        })

    # Geography ONLY when the copy actually opens on it. A niched email makes no
    # location claim about the prospect, but the word still appears in the body
    # because a GIFT LEAD is based there — underlining that would attach the
    # prospect's city to a sentence about someone else entirely.
    if not niche and gift.geo_level in ("city", "state"):
        for value, label in ((prospect.city, "city"), (prospect.state, "state")):
            said = (value or "").strip().lower()
            if said:
                out.append({
                    "text": said, "label": label, "quote": value or "",
                    "how": "from the Apollo export, NOT from their site", "url": "",
                })

    return [c for c in out if c["text"] and c["text"] in body]


def build_review(
    prospect: Prospect,
    gift: Gift,
    research: Any,
    email1: Any,
    followups: list[Any],
    followup_leads: list[Any],
    row: dict[str, Any],
    dms: dict[str, str] | None = None,
    sounds_off: list[dict[str, str]] | None = None,
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
        # Claims about the PROSPECT, attached to the words that make them. The
        # gate underlines these in the copy and shows the proof on hover, which
        # is what the bottom-of-card evidence list used to be for.
        "claims": _claims(prospect, gift, research, getattr(email1, "body", "")),
        "flags": flags,
        # Advisory, and kept OUT of `flags` on purpose: those are stop-signs a
        # human has to clear, these are suggestions. Mixing them would teach the
        # operator to skim the box that matters.
        "sounds_off": list(sounds_off or []),
        "leads": leads,
        # editable copy. `email_1` is split at the seam between the part that
        # varies per prospect and the closing that is byte-identical on every
        # card: the gate edits the head and dims the tail, then re-joins them.
        "subject": getattr(email1, "subject", ""),
        "email_1": getattr(email1, "body", ""),
        "email_1_head": getattr(email1, "head", getattr(email1, "body", "")),
        "email_1_tail": getattr(email1, "shared_tail", ""),
        "email_2": getattr(followups[0], "body", "") if followups else "",
        "email_3": getattr(followups[1], "body", "") if len(followups) > 1 else "",
        # The LinkedIn half, editable on the same card: one review pass covers
        # both channels, and an edit here reaches the exported CSV.
        "li_dm_1": (dms or {}).get("li_dm_1", ""),
        "li_dm_1_evergreen": (dms or {}).get("li_dm_1_evergreen", ""),
        "li_dm_2": (dms or {}).get("li_dm_2", ""),
    }
