"""The ONLY place the LLM touches Email #1: the freeform per-lead
descriptions ("what they did, plain words"). Everything structural —
subject, framing, CTA, template, dates — is deterministic code elsewhere.

OpenAI (chosen in the build plan). Requires OPENAI_API_KEY; import is
cheap, the key is only needed when you actually call describe_leads().
The honesty rules are also enforced in code (copy.honesty), so a
misbehaving model can't leak a date or dollar amount into a sent email —
this prompt is the first line, strip_dollar_amounts/date_suffix the second.
"""

from __future__ import annotations

import json

from system_b.gift.models import Gift, Prospect
from system_b.models import Lead

_SYSTEM = (
    "You write one short, plain-words clause describing what a company did, "
    "for a casual lowercase cold email from a lead-sourcing tool to a "
    "fractional CFO. Rules: lowercase; no greeting; one clause, not a "
    "sentence; describe only the signal (what they did). NEVER include a "
    "dollar amount for a raise (the figure is a filing target, not money "
    "raised). NEVER include a date or 'X days/weeks ago' — dates are added "
    "separately. Do not name the CFO or the prospect firm."
)


def _lead_brief(lead: Lead) -> dict[str, str | None]:
    return {
        "id": lead.id,
        "company": lead.company,
        "signal_type": lead.signal_type,
        "value_prop": lead.value_prop,
        "raw_signal": lead.signals[0].plain_words_description if lead.signals else None,
    }


def describe_leads(
    gift: Gift,
    prospect: Prospect,
    *,
    model: str = "gpt-4o-mini",
) -> dict[str, str]:
    """Return {lead_id: plain-words description}. Structural/honesty layers
    still run on top of whatever comes back."""
    from openai import OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    briefs = [_lead_brief(l) for l in gift.leads]
    user = (
        "Write a description clause for each lead. Return JSON "
        '{"descriptions": [{"id": "...", "text": "..."}]}.\n\n'
        f"leads: {json.dumps(briefs)}"
    )
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    out: dict[str, str] = {}
    for row in data.get("descriptions", []):
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = str(row.get("text", "")).strip()
    return out
