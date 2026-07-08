"""The LLM proposer for Step 2a. It only PROPOSES; classifier.py re-verifies
every fact against the fetched pages, so the model cannot introduce a claim
that isn't on the site. OpenAI, injectable (classify() takes any LlmFn).
"""

from __future__ import annotations

import json
from typing import Any

_SYSTEM = (
    "You classify a fractional-CFO firm's website as niched or generalist, "
    "for lead matching. Rules:\n"
    "1. If they state a served industry outright (e.g. 'we serve healthcare "
    "startups') -> niched, path='statement'. Put their EXACT words in "
    "niche_phrase, copied verbatim from the page, and a one-word industry in "
    "niche_guess.\n"
    "2. Else if a client list makes it obvious (3+ named clients in the same "
    "industry, all SMBs; ignore one-off or big-brand logos) -> niched, "
    "path='client_list'. List the client names verbatim; put the industry in "
    "niche_guess.\n"
    "3. Anything else, including thin sites -> generalist.\n"
    "NEVER invent a phrase or client name. Copy strings exactly as they "
    "appear or omit them — a downstream check rejects anything not found "
    "verbatim on the page."
)


def classify_site(site: dict[str, str], *, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """Return the raw proposal dict for classifier.classify()."""
    from openai import OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    pages = "\n\n".join(f"URL: {url}\n{text[:6000]}" for url, text in site.items())
    user = (
        "Classify this firm. Return JSON with keys: classification "
        "('niched'|'generalist'), path ('statement'|'client_list'|''), "
        "niche_phrase, niche_guess, clients (list of {name}).\n\n"
        f"{pages}"
    )
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content or "{}")
