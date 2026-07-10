"""Gate B — genuine value_prop fit check (the honest gate).

System A assigns each lead a coarse industry tag, and it is sometimes WRONG
(an IT/defense firm bucketed `manufacturing`). Tier 1/2 make an explicit claim
— "you work with [niche] companies, here's a [niche] company" — so trusting the
tag alone lets a false claim through. Before a niche is claimed, this asks an
LLM whether each gift lead's value_prop genuinely READS as that niche. Code
enforces the gate (resolver drops the tier unless every gift lead passes); the
LLM only judges fit, it can't introduce a claim. Injectable so tests stay
offline and deterministic.
"""

from __future__ import annotations

import json

from system_b.models import Lead

_SYSTEM = (
    "You verify whether companies genuinely operate in a given industry — an "
    "honesty check before a cold email claims the recipient works with that "
    "industry. You get an industry label and companies with a short "
    "description. For EACH company, answer fits=true ONLY if its description "
    "clearly reads as that industry; answer false if it's a different industry "
    "or you can't tell. Be strict: vague, adjacent, or off-industry descriptions "
    'are false. Return JSON {"verdicts": [{"id": "...", "fits": true|false}]}.'
)


def fit_check(niche_label: str, leads: list[Lead], *, model: str = "gpt-4o-mini") -> list[bool]:
    """Per-lead booleans (aligned with `leads`): does each lead's value_prop
    genuinely read as a `niche_label` company? Missing/omitted leads default to
    False (strict — never claim fit we didn't get)."""
    if not leads:
        return []

    from openai import OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    items = [
        {"id": l.id, "company": l.company, "description": l.value_prop or ""}
        for l in leads
    ]
    user = f"industry label: {niche_label}\ncompanies: {json.dumps(items)}"
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    by_id: dict[str, bool] = {}
    for v in data.get("verdicts", []):
        if isinstance(v, dict) and v.get("id") is not None:
            by_id[str(v["id"])] = bool(v.get("fits"))
    return [by_id.get(l.id, False) for l in leads]
