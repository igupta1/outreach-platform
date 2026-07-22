"""B7 — the quota-driven daily run.

The operator asks for N emails; the run produces exactly that many pending
cards, DUE FOLLOW-UPS FIRST, then new first-touches from the pending queue with
whatever quota remains. DAILY_SEND_CAP is a hard ceiling above the quota.

`guard_unready_followups` is the B5 timing guard: pause any lead whose next
step is due but whose follow-up isn't approved yet, so Smartlead never sends a
blank {{email_2/3}}.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from system_b import config
from system_b.cadence import DEFAULT_CADENCE, Step, day_for, next_dm_step
from system_b.clients.inventory import load_taxonomy, snapshot_for_niche
from system_b.sending.base import EmailSender
from system_b.sequence.generate import (
    generate_first_touch,
    generate_followup,
    generate_linkedin,
)
from system_b.sequence.rows import field, record_to_row, resolve_pack_key

_SENT_STAGES = ("email_1_sent", "email_2_sent")
_NEW_STAGES = ("researched", "", None)


def find_due_followups(records: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """In-sequence rows whose next follow-up is due: at a sent stage, approved
    (no in-flight draft), not frozen, due_date reached. Most-overdue first."""
    out = []
    for r in records:
        f = r["fields"]
        if f.get("frozen"):
            continue
        if f.get("stage") not in _SENT_STAGES:
            continue
        if (f.get("review_status") or "") != "approved":
            continue
        due = f.get("due_date")
        if due and due <= today.isoformat():
            out.append(r)
    return sorted(out, key=lambda r: r["fields"].get("due_date") or "")


def find_new_prospects(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows never drafted yet: at 'researched', no review_status, has a website,
    not frozen. This is the pending prospect queue (H1)."""
    out = []
    for r in records:
        f = r["fields"]
        if f.get("frozen"):
            continue
        if f.get("stage") not in _NEW_STAGES:
            continue
        if (f.get("review_status") or ""):
            continue
        if not f.get("website"):
            continue
        out.append(r)
    return out


def find_due_linkedin(
    records: list[dict[str, Any]], today: date,
    cadence: tuple[Step, ...] = DEFAULT_CADENCE,
) -> list[tuple[dict[str, Any], str]]:
    """LinkedIn DMs due (F2): the sequence started, connection accepted (gate),
    not frozen (= no reply on either channel), no LinkedIn card already pending,
    and the next DM's cadence day reached. Most-overdue first. Returns (record, step)."""
    due: list[tuple[dict[str, Any], str, str]] = []
    for r in records:
        f = r["fields"]
        if f.get("frozen") or f.get("stage") == "do_not_contact":
            continue
        started = f.get("sequence_started_at")
        if not started:
            continue
        if not f.get("connection_accepted"):          # F3 gate: DM only if connected
            continue
        if (f.get("li_review_status") or "") == "pending":
            continue                                   # a LinkedIn card is already in flight
        step = next_dm_step(f.get("li_progress"))
        if step is None:
            continue                                   # dm_2 already done
        day = day_for(step, cadence)
        if day is None:
            continue
        try:
            due_on = (date.fromisoformat(str(started)[:10]) + timedelta(days=day)).isoformat()
        except ValueError:
            continue
        if due_on <= today.isoformat():
            due.append((r, step, due_on))
    due.sort(key=lambda x: x[2])
    return [(r, step) for r, step, _ in due]


def _all_records(at: Any, max_records: int = 5000) -> list[dict[str, Any]]:
    return at.table.all(max_records=max_records)


def quota_run(
    at: Any,
    *,
    email_quota: int,
    linkedin_quota: int = 0,
    today: date | None = None,
    pack_default: str = "cfo",
    send_cap: int | None = None,
    records: list[dict[str, Any]] | None = None,
    scraper_override: Any = None,
    taxonomy_override: dict | None = None,
) -> dict[str, Any]:
    """Generate up to `email_quota` email cards (due follow-ups first, then new
    first-touches) AND up to `linkedin_quota` LinkedIn DM cards (most-overdue
    first). Independent budgets. Writes only pending review cards.

    Each row is served from ITS OWN niche inventory (`niche_pack`), built on
    demand and cached. Tests can pin one inventory/taxonomy via the
    `*_override` params."""
    today = today or date.today()
    cap = send_cap if send_cap is not None else config.DAILY_SEND_CAP
    quota = max(0, min(email_quota, cap))
    if records is None:
        records = _all_records(at)

    _scrapers: dict[str, Any] = {}

    def scraper_for(pack_key: str) -> Any:
        if scraper_override is not None:
            return scraper_override
        if pack_key not in _scrapers:
            _scrapers[pack_key] = snapshot_for_niche(pack_key, today=today)
        return _scrapers[pack_key]

    taxonomy = taxonomy_override if taxonomy_override is not None else load_taxonomy()

    results: list[dict[str, Any]] = []
    generated = 0

    for r in find_due_followups(records, today):
        if generated >= quota:
            break
        pack_key = resolve_pack_key(r["fields"])
        try:
            res = generate_followup(at, scraper_for(pack_key), r, today)
        except Exception as exc:  # noqa: BLE001 — surface, never abort the run
            res = {"firm": r["fields"].get("firm_name", "?"), "status": "error",
                   "step": 2, "error": repr(exc)}
        results.append(res)
        if res.get("status") == "ok":
            generated += 1

    if generated < quota:
        for r in find_new_prospects(records):
            if generated >= quota:
                break
            row = record_to_row(r)
            if not row["website"]:
                continue
            pack_key = field(r["fields"], "niche_pack", "") or pack_default
            try:
                res = generate_first_touch(
                    at, scraper_for(pack_key), taxonomy, row, today, pack_key=pack_key
                )
            except Exception as exc:  # noqa: BLE001
                res = {"firm": row["firm_name"], "status": "error", "step": 1, "error": repr(exc)}
            results.append(res)
            if res.get("status") == "ok":
                generated += 1

    # LinkedIn DMs — independent budget, most-overdue first.
    li_generated = 0
    if linkedin_quota > 0:
        for r, step in find_due_linkedin(records, today):
            if li_generated >= linkedin_quota:
                break
            try:
                res = generate_linkedin(at, r, step, today)
            except Exception as exc:  # noqa: BLE001
                res = {"firm": r["fields"].get("firm_name", "?"), "status": "error",
                       "channel": "linkedin", "step": step, "error": repr(exc)}
            results.append(res)
            if res.get("status") == "ok":
                li_generated += 1

    email_results = [x for x in results if x.get("channel") != "linkedin"]
    followups = sum(1 for x in email_results if x.get("step", 1) != 1 and x.get("status") == "ok")
    first = sum(1 for x in email_results if x.get("step") == 1 and x.get("status") == "ok")
    return {
        "quota": quota, "generated": generated, "capped_at": cap,
        "followups": followups, "first_touches": first,
        "linkedin_quota": linkedin_quota, "linkedin_generated": li_generated,
        "results": results,
    }


def guard_unready_followups(
    at: Any, sender: EmailSender, today: date | None = None,
    *, records: list[dict[str, Any]] | None = None,
) -> list[str]:
    """B5 timing guard: pause any lead whose next step is due but whose follow-up
    isn't approved (variable not set) — better a paused thread than a blank send.
    Returns the record ids paused."""
    today = today or date.today()
    if records is None:
        records = _all_records(at)
    paused: list[str] = []
    for r in records:
        f = r["fields"]
        if f.get("frozen") or f.get("stage") not in _SENT_STAGES:
            continue
        if (f.get("review_status") or "") == "approved":
            continue                                     # follow-up already set/sent
        due = f.get("due_date")
        lead_id = field(f, "smartlead_lead_id", "")
        campaign_id = field(f, "smartlead_campaign_id", "")
        if due and due <= today.isoformat() and lead_id and campaign_id:
            sender.pause_lead(campaign_id, lead_id)
            at.update(r["id"], {"frozen": True, "next_action": "PAUSED: follow-up not ready in time"})
            paused.append(r["id"])
    return paused
