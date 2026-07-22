"""Step 10 review card — the single human-readable block assembled into the
prospect's Airtable row (the `review_card` field). Everything the reviewer
needs to approve/edit/reject in one place.

Note: the live API has no `score`, so the card shows match level, signal
type, freshness, date + date_confidence, and finance_grade when present —
not a numeric score. Best lead is marked ★.
"""

from __future__ import annotations

from typing import Any

from system_b.gift.engine import compute_match_level
from system_b.gift.models import Gift, Prospect

INBOX_NOTE = "auto (mason / william / wendell)"


def _lead_dict(lead: Any, prospect: Prospect, best_id: str | None) -> dict[str, Any]:
    return {
        "company": lead.company,
        "value_prop": lead.value_prop,
        "domain": lead.domain,
        "domainless": lead.domain is None,
        "signal_type": lead.signal_type,
        "date": lead.newest_date or None,
        "date_confidence": lead.effective_date_confidence,
        "match_level": compute_match_level(lead, prospect),
        "freshness": lead.freshness,
        "best": best_id is not None and lead.id == best_id,
    }


def _prospect_dict(prospect: Prospect, contact: dict[str, str] | None) -> dict[str, Any]:
    mp = prospect.match_param
    return {
        "firm_name": prospect.firm_name,
        "first_name": prospect.first_name,
        "city": prospect.city,
        "state": prospect.state,
        "email": (contact or {}).get("email", ""),
        "linkedin": (contact or {}).get("linkedin", ""),
        "classification": prospect.classification,
        "niche_exclusivity": prospect.niche_exclusivity,
        "match_param": f"{mp[0]}={mp[1]}" if mp else None,
        "niche_phrase": prospect.niche_phrase,
        "niche_source": prospect.niche_source,
    }


def card_payload_email1(
    prospect: Prospect, gift: Gift, draft: Any, research: Any, flags: list[str],
    *, contact: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Structured Email #1 card for the Track H flashcard screen (H3)."""
    evidence = []
    if research is not None and getattr(research, "evidence", None):
        evidence = [{"kind": e.kind, "text": e.text, "url": e.url} for e in research.evidence]
    return {
        "channel": "email",
        "step": 1,
        "step_label": "Email 1 of 3",
        "prospect": _prospect_dict(prospect, contact),
        "evidence": evidence,
        "message": {"subject": draft.subject, "body": draft.body},
        "left_field_variant": getattr(draft, "left_field_variant", ""),
        "sending_inbox": INBOX_NOTE,
        "signoff_note": "added by the sending mailbox's signature",
        "gift_leads": [_lead_dict(l, prospect, gift.best_lead.id) for l in gift.leads],
        "flags": list(flags),
        "history": [],
    }


def card_payload_linkedin(
    prospect: Prospect, message: str, *, step: str, history: list[str] | None = None,
    contact: dict[str, str] | None = None, flags: list[str] | None = None,
) -> dict[str, Any]:
    """Structured LinkedIn DM card (F2). No gift leads — DMs point back at the
    email thread. step is 'dm_1' or 'dm_2'."""
    n = {"dm_1": 1, "dm_2": 2}.get(step, 1)
    return {
        "channel": "linkedin",
        "step": step,
        "step_label": f"DM {n} of 2",
        "prospect": _prospect_dict(prospect, contact),
        "evidence": [],
        "message": {"subject": "", "body": message},
        "left_field_variant": "",
        "sending_inbox": "your LinkedIn (sent by hand)",
        "signoff_note": "",
        "gift_leads": [],
        "flags": list(flags or []),
        "history": list(history or []),
    }


def card_payload_followup(
    prospect: Prospect, lead: Any, draft: Any, flags: list[str],
    *, step: int, history: list[str] | None = None, contact: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Structured Email #2/#3 card (H3, with sequence history)."""
    return {
        "channel": "email",
        "step": step,
        "step_label": f"Email {step} of 3",
        "prospect": _prospect_dict(prospect, contact),
        "evidence": [],
        "message": {"subject": draft.subject, "body": draft.body},
        "left_field_variant": "",
        "sending_inbox": INBOX_NOTE,
        "signoff_note": "added by the sending mailbox's signature",
        "gift_leads": [_lead_dict(lead, prospect, lead.id)] if lead is not None else [],
        "flags": list(flags),
        "history": list(history or []),
    }


def build_card(
    prospect: Prospect,
    gift: Gift,
    draft: Any,
    research: Any,
    flags: list[str],
    *,
    contact: dict[str, str] | None = None,
) -> str:
    L: list[str] = ["═══════════ REVIEW CARD ═══════════"]

    # 1. Prospect
    L.append(f"1. PROSPECT: {prospect.firm_name}")
    loc = ", ".join(x for x in (prospect.city, prospect.state) if x)
    if loc:
        L.append(f"   location: {loc}")
    if prospect.first_name:
        L.append(f"   contact: {prospect.first_name}")
    if contact:
        if contact.get("email"):
            L.append(f"   email: {contact['email']}")
        if contact.get("linkedin"):
            L.append(f"   linkedin: {contact['linkedin']}")

    # 2. Classification + how we know
    if prospect.classification == "niched" and prospect.match_param:
        kind, val = prospect.match_param
        how = {"site": "stated on their site", "client_list": "named client list"}.get(
            prospect.niche_source, "classified"
        )
        label = prospect.niche_phrase or val
        L.append(f'2. CLASSIFICATION: niched — "{label}" → {kind}={val}  (how we know: {how})')
        verb = {"sole": "work with", "one_of_several": "work with"}.get(
            prospect.niche_exclusivity, ""
        )
        L.append(f'   niche_exclusivity: {prospect.niche_exclusivity}  → framing verb: "{verb}"')
    else:
        L.append("2. CLASSIFICATION: generalist")
        if prospect.niche_phrase:
            L.append(f'   note: stated niche "{prospect.niche_phrase}" saved but unmapped — never claimed')

    # 3. Evidence
    L.append("3. EVIDENCE:")
    if research is not None and getattr(research, "evidence", None):
        for e in research.evidence:
            L.append(f'   [{e.kind}] "{e.text}" — {e.url}')
    else:
        L.append("   (none — generalist)")

    # 4. Gift / lead detail
    L.append(f"4. GIFT — {gift.gift_size} lead(s):")
    for l in gift.leads:
        best = " ★BEST" if l.id == gift.best_lead.id else ""
        lvl = compute_match_level(l, prospect)
        L.append(f"   • {l.company}{best}  [{l.signal_type}]  match L{lvl}")
        if l.value_prop:
            L.append(f"       value_prop: {l.value_prop}")
        L.append(f"       domain: {l.domain or 'DOMAINLESS'}")
        fg = f"  finance_grade={l.finance_grade}" if l.finance_grade else ""
        L.append(f"       {l.freshness}  date={l.newest_date or '?'} ({l.effective_date_confidence}){fg}")

    # 5. Honesty values
    L.append(
        f"5. HONESTY: all_niche={gift.all_niche}  niche_exclusivity={prospect.niche_exclusivity}  "
        f"geo_level={gift.geo_level}  subject_shape={gift.subject_shape}  what={gift.what_category}"
    )

    # 6. Flags
    if flags:
        L.append(f"6. FLAGS ({len(flags)}):")
        for f in flags:
            L.append(f"   ⚠ {f}")
    else:
        L.append("6. FLAGS: none")

    # 7. The exact message about to send
    L.append("7. QUEUED MESSAGE:")
    variant = getattr(draft, "left_field_variant", "")
    if variant:
        L.append(f"   left-field variant: {variant}")
    L.append(f"   Subject: {draft.subject}")
    for line in draft.body.split("\n"):
        L.append(f"   {line}" if line else "")

    # 8. Decision
    L.append("8. DECISION: approve / edit / reject")
    return "\n".join(L)


def build_followup_card(
    prospect: Prospect,
    lead: Any,
    draft: Any,
    flags: list[str],
    *,
    step: int,
    history: list[str] | None = None,
    contact: dict[str, str] | None = None,
    sending_inbox: str | None = None,
) -> str:
    """B8 — the review card for Email #2 / #3. Shows step position, the one NEW
    gift lead (or a fallback note), the full sequence history to this prospect,
    and the exact threaded (blank-subject) message. `lead` is None for a
    fallback bump."""
    L: list[str] = [f"═══════ REVIEW CARD — FOLLOW-UP (Email {step} of 3) ═══════"]

    # 1. Prospect
    L.append(f"1. PROSPECT: {prospect.firm_name}")
    loc = ", ".join(x for x in (prospect.city, prospect.state) if x)
    if loc:
        L.append(f"   location: {loc}")
    if prospect.first_name:
        L.append(f"   contact: {prospect.first_name}")
    if contact:
        if contact.get("email"):
            L.append(f"   email: {contact['email']}")
        if contact.get("linkedin"):
            L.append(f"   linkedin: {contact['linkedin']}")

    # 2. Step / channel / inbox — the signoff is owned by the sending mailbox
    #    (B4a), so the reviewer sees which persona will sign it.
    inbox = sending_inbox or "auto (mason / william / wendell)"
    L.append(f"2. STEP: Email {step} of 3   channel: email   threaded reply (blank subject)")
    L.append(f"   sending inbox: {inbox}  →  signoff added by that mailbox's signature")

    # 3. The one new lead this follow-up gifts (or the fallback bump)
    if lead is not None:
        lvl = compute_match_level(lead, prospect)
        L.append(f"3. NEW LEAD:  {lead.company}  [{lead.signal_type}]  match L{lvl}")
        if lead.value_prop:
            L.append(f"       value_prop: {lead.value_prop}")
        L.append(f"       domain: {lead.domain or 'DOMAINLESS'}")
        L.append(f"       {lead.freshness}  date={lead.newest_date or '?'} ({lead.effective_date_confidence})")
    else:
        L.append("3. NEW LEAD: none available — fallback bump (no new lead claimed)")

    # 4. Flags
    if flags:
        L.append(f"4. FLAGS ({len(flags)}):")
        for f in flags:
            L.append(f"   ⚠ {f}")
    else:
        L.append("4. FLAGS: none")

    # 5. Sequence history — every prior touch (non-negotiable context, B8)
    L.append("5. SEQUENCE HISTORY:")
    if history:
        for h in history:
            for line in h.split("\n"):
                L.append(f"   {line}" if line else "")
    else:
        L.append("   (email #1 sent; history not recorded)")

    # 6. The exact threaded message
    L.append("6. QUEUED MESSAGE (blank subject — threads under Email #1):")
    for line in draft.body.split("\n"):
        L.append(f"   {line}" if line else "")

    # 7. Decision
    L.append("7. DECISION: approve / edit / reject")
    return "\n".join(L)
