"""B3 — draft generation for the sequence.

Every niche runs the SAME pipeline now: research the prospect's site → classify
the customer vertical they serve (verbatim, Gate A) → `resolve_gift` builds a
vertical-matched gift (Gate B) or falls back to a generalist geo gift → LLM
per-lead descriptions → a pending Email #1 card. The caller supplies the
per-niche inventory scraper (`clients.inventory.snapshot_for_niche`), so this
module is niche-blind — it just threads the row's `pack` through.

`generate_first_touch` writes a pending Email #1 card. `generate_followup`
pulls ONE new lead (exclude_ids = everything already sent) for Email #2/#3, or a
fallback bump when the well is dry. Both leave review_status=pending — nothing
is sent here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from system_b.copy.email import build_email_1, build_followup_email
from system_b.copy.lex import niche_display
from system_b.copy.linkedin import build_dm
from system_b.copy.llm import describe_leads
from system_b.gift.engine import build_gift
from system_b.gift.tiering import resolve_gift
from system_b.niches.base import pack_for
from system_b.research.service import research_and_write
from system_b.review import (
    assemble_followup_review,
    assemble_linkedin_review,
    assemble_review,
)
from system_b.sequence.rows import (
    field,
    next_step_for,
    parse_history,
    parse_id_list,
    prospect_from_row,
    resolve_pack_key,
)


def generate_first_touch(
    at: Any, sc: Any, taxonomy: dict, row: dict[str, Any], today: date,
    *, pack_key: str = "cfo",
) -> dict[str, Any]:
    """Research + gift + Email #1 (no signoff), written as a pending card.

    Runs for EVERY niche: research the site, classify the served vertical, build
    a vertical-matched gift (or a generalist geo gift as the fallback). `sc` is
    the row's per-niche inventory scraper; `pack_key` selects the copy voice and
    lead preference."""
    rid = row["record_id"]
    pack = pack_for(pack_key)
    research = research_and_write(rid, row["website"], taxonomy, at)
    prospect, gift = resolve_gift(research, row, sc, pack=pack)
    if gift is None:
        return {"firm": row.get("firm_name"), "status": "no_gift", "step": 1}
    descriptions = describe_leads(gift, prospect, pack=pack)
    draft = build_email_1(
        gift, prospect, descriptions, today=today, pack=pack, include_signoff=False
    )
    contact = {"email": row.get("email", ""), "linkedin": row.get("linkedin", "")}
    assemble_review(
        at, rid, prospect, gift, draft, research,
        contact=contact, niche_pack=pack_key,
    )
    return {
        "firm": row["firm_name"], "status": "ok", "step": 1,
        "subject": draft.subject, "gift_size": gift.gift_size,
    }


def generate_followup(at: Any, sc: Any, record: dict[str, Any], today: date) -> dict[str, Any]:
    """Draft the next follow-up for an in-sequence prospect. `record` is a full
    Airtable record ({'id', 'fields'}); `sc` is the row's per-niche inventory."""
    fields = record["fields"]
    rid = record["id"]
    firm = field(fields, "firm_name", "?")
    if fields.get("frozen"):
        return {"firm": firm, "status": "skipped_frozen"}
    step = next_step_for(fields.get("stage"))
    if step is None:
        return {"firm": firm, "status": "sequence_complete"}

    pack_key = resolve_pack_key(fields)
    pack = pack_for(pack_key)
    prospect = prospect_from_row(fields)

    gift = build_gift(prospect, sc, target=1, pack=pack)   # excludes already-sent
    lead = gift.leads[0] if gift else None
    description = ""
    if lead is not None:
        description = describe_leads(gift, prospect, pack=pack).get(lead.id, "")

    draft = build_followup_email(
        lead, prospect, description, step=step, today=today, pack=pack, include_signoff=False
    )
    contact = {"email": field(fields, "email", ""), "linkedin": field(fields, "linkedin", "")}
    history = parse_history(fields.get("message_history"))
    assemble_followup_review(
        at, rid, prospect, lead, draft, step=step, history=history, contact=contact
    )
    return {
        "firm": firm, "status": "ok", "step": step,
        "kind": "value" if lead is not None else "fallback",
    }


def generate_linkedin(at: Any, record: dict[str, Any], step: str, today: date) -> dict[str, Any]:
    """F2 — draft a LinkedIn DM (dm_1|dm_2) as a pending LinkedIn card. Copy is
    LIFTED (no LLM); it references the email thread, describes no leads."""
    fields = record["fields"]
    rid = record["id"]
    firm = field(fields, "firm_name", "?")
    if fields.get("frozen"):
        return {"firm": firm, "status": "skipped_frozen", "channel": "linkedin"}

    pack = pack_for(resolve_pack_key(fields))
    prospect = prospect_from_row(fields)
    all_niche = bool(fields.get("all_niche"))
    ctx = {
        "n": len(parse_id_list(fields.get("sent_lead_ids"))),
        "all_niche": all_niche,
        "niche": niche_display(prospect.match_param) if all_niche else None,
        "best_cfo_company": field(fields, "li_best_cfo", "") or None,
    }
    body = build_dm(step, prospect, ctx, pack=pack)
    contact = {"email": field(fields, "email", ""), "linkedin": field(fields, "linkedin", "")}
    history = parse_history(fields.get("message_history"))
    assemble_linkedin_review(at, rid, prospect, body, step=step, history=history, contact=contact)
    return {"firm": firm, "status": "ok", "step": step, "channel": "linkedin"}
