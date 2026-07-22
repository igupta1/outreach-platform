"""Pure helpers for reading/writing the Airtable prospect row shape used by
the sequence layer. No network, no side effects — trivially testable.
"""

from __future__ import annotations

from typing import Any

from system_b import config
from system_b.gift.models import Prospect


class NotEligibleError(RuntimeError):
    """Raised when a push is attempted for a prospect not marked eligible_for_send.
    A distinct type so callers can surface the safety-gate refusal explicitly."""


# stage -> the follow-up step to draft next (email_1_sent means step 2 is next).
_NEXT_STEP = {"email_1_sent": 2, "email_2_sent": 3}


def field(fields: dict[str, Any], key: str, default: Any = "") -> Any:
    return fields.get(key) if fields.get(key) not in (None, "") else default


def parse_match_param(raw: str | None) -> tuple[str, str] | None:
    """'niche=dental' -> ('niche', 'dental'); blank/malformed -> None."""
    if not raw or "=" not in raw:
        return None
    kind, val = raw.split("=", 1)
    kind, val = kind.strip(), val.strip()
    return (kind, val) if kind and val else None


def parse_id_list(raw: str | None) -> list[str]:
    """A newline/comma-separated id blob -> a clean list."""
    if not raw:
        return []
    out: list[str] = []
    for chunk in str(raw).replace(",", "\n").splitlines():
        c = chunk.strip()
        if c:
            out.append(c)
    return out


def join_id_list(ids: list[str]) -> str:
    return "\n".join(dict.fromkeys(i for i in ids if i))   # dedup, keep order


def parse_queued_message(text: str | None) -> tuple[str, str]:
    """Split 'Subject: X\\n\\n<body>' back into (subject, body). Follow-ups have
    a blank subject. Robust to an edited message with no Subject line."""
    if not text:
        return "", ""
    lines = text.split("\n")
    if lines and lines[0].startswith("Subject:"):
        subject = lines[0][len("Subject:"):].strip()
        rest = lines[1:]
        while rest and rest[0].strip() == "":
            rest = rest[1:]
        return subject, "\n".join(rest)
    return "", text


def next_step_for(stage: str | None) -> int | None:
    """The follow-up step to draft given the current stage, or None if done."""
    return _NEXT_STEP.get(stage or "")


# --- sequence history (message_history field) -----------------------------

HISTORY_SEP = "\n----------\n"


def parse_history(raw: str | None) -> list[str]:
    """Split the stored message_history blob into individual prior messages."""
    if not raw:
        return []
    return [blk.strip() for blk in raw.split(HISTORY_SEP) if blk.strip()]


def history_entry(step: int, subject: str, body: str, sent_on: str) -> str:
    """A single history block: what was sent, which step, when."""
    head = f"[Email {step} · {sent_on}]"
    if subject:
        head += f" subject: {subject}"
    return f"{head}\n{body}"


def append_history(existing: str | None, entry: str) -> str:
    blocks = parse_history(existing)
    blocks.append(entry)
    return HISTORY_SEP.join(blocks)


def prospect_from_row(fields: dict[str, Any]) -> Prospect:
    """Rebuild the Prospect a follow-up needs from a stored row (the original
    in-memory Prospect is long gone by the next night)."""
    return Prospect(
        firm_name=field(fields, "firm_name", ""),
        city=field(fields, "city", None) or None,
        state=field(fields, "state", None) or None,
        classification=field(fields, "classification", "generalist") or "generalist",
        match_param=parse_match_param(fields.get("match_param")),
        niche_phrase=field(fields, "niche_phrase", None) or None,
        niche_source=field(fields, "niche_source", "site") or "site",
        first_name=field(fields, "first_name", None) or None,
        niche_exclusivity=field(fields, "niche_exclusivity", "none") or "none",
        sent_lead_ids=parse_id_list(fields.get("sent_lead_ids")),
    )


def record_to_row(record: dict[str, Any]) -> dict[str, Any]:
    """Map a full Airtable record to the flat 'row' dict the first-touch
    generator expects (mirrors m4_walkthrough.load_prospects)."""
    f = record["fields"]
    return {
        "record_id": record["id"],
        "firm_name": field(f, "firm_name", ""),
        "website": field(f, "website", ""),
        "city": field(f, "city", None) or None,
        "state": field(f, "state", None) or None,
        "first_name": field(f, "first_name", None) or None,
        "email": field(f, "email", ""),
        "linkedin": field(f, "linkedin", ""),
    }


def resolve_pack_key(fields: dict[str, Any]) -> str:
    return field(fields, "niche_pack", "cfo") or "cfo"


def resolve_campaign(fields: dict[str, Any], pack_key: str) -> str:
    """The Smartlead campaign for this row: the id already stored on it, else
    the per-niche default from config. Raises if neither is set."""
    cid = field(fields, "smartlead_campaign_id", "") or config.SMARTLEAD_CAMPAIGN_IDS.get(pack_key)
    if not cid:
        raise RuntimeError(
            f"no Smartlead campaign for pack {pack_key!r} — set SMARTLEAD_CAMPAIGN_IDS "
            f"(e.g. '{pack_key}:<campaign_id>') or the row's smartlead_campaign_id"
        )
    return str(cid)
