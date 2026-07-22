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
    "for a casual lowercase cold email from a lead-sourcing tool to a service "
    "provider (a fractional cfo, accountant, managed-it/security/cloud shop, "
    "etc.). Ground the clause in the lead's `raw_signal` and `signal_type` — "
    "describe ONLY that signal (what they did), nothing you can't see. Rules: "
    "lowercase; no greeting; one clause, not a sentence. NEVER include a dollar "
    "amount for a raise (the figure is a filing target, not money raised). "
    "NEVER include a date or 'X days/weeks ago' — dates are added separately. "
    "Do not name the reader or the prospect firm."
)


def _raw_signal(lead: Lead) -> str | None:
    """The lead's own precomputed plain-words line — the honest fallback when the
    model returns nothing for this lead."""
    return next(
        (s.plain_words_description for s in lead.signals if s.plain_words_description),
        None,
    )


def _lead_brief(lead: Lead) -> dict[str, str | None]:
    return {
        "id": lead.id,
        "company": lead.company,
        "signal_type": lead.signal_type,
        "value_prop": lead.value_prop,
        "raw_signal": _raw_signal(lead),
    }


def describe_leads(
    gift: Gift,
    prospect: Prospect,
    *,
    pack: object | None = None,
    model: str = "gpt-4o-mini",
) -> dict[str, str]:
    """Return {lead_id: plain-words description} for ANY niche. Each lead is
    seeded with its own precomputed `plain_words_description` (the honest
    fallback), then overlaid with the model's clause when it returns one — so a
    line is never fabricated and never missing. Structural/honesty layers still
    run on top of whatever comes back.

    `pack` is the caller's active NichePack (the pipeline passes it as a keyword).
    It is accepted for a uniform call signature across niches; the per-lead line
    is grounded in each lead's own `signals[].plain_words_description` and
    `signal_type`, which are already niche-specific, so no pack-conditional
    branching is needed here."""
    from openai import OpenAI

    from system_b import config

    # Seed every lead with its grounded fallback so a line exists even if the
    # model omits a lead (or the call is skipped entirely).
    out: dict[str, str] = {}
    for l in gift.leads:
        fallback = _raw_signal(l)
        if fallback:
            out[l.id] = fallback

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    briefs = [_lead_brief(l) for l in gift.leads]
    user = (
        "Write a description clause for each lead, grounded in its raw_signal. "
        'Return JSON {"descriptions": [{"id": "...", "text": "..."}]}.\n\n'
        f"leads: {json.dumps(briefs)}"
    )
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    for row in data.get("descriptions", []):
        if isinstance(row, dict) and row.get("id"):
            text = str(row.get("text", "")).strip()
            if text:
                out[str(row["id"])] = text
    return out
