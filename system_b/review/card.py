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
        f"5. HONESTY: all_niche={gift.all_niche}  geo_level={gift.geo_level}  "
        f"subject_shape={gift.subject_shape}  what={gift.what_category}"
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
    L.append(f"   Subject: {draft.subject}")
    for line in draft.body.split("\n"):
        L.append(f"   {line}" if line else "")

    # 8. Decision
    L.append("8. DECISION: approve / edit / reject")
    return "\n".join(L)
