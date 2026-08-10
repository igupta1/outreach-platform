"""The LLM proposer for Step 2a. It only PROPOSES; classifier.py re-verifies
every fact against the fetched pages, so the model cannot introduce a claim
that isn't on the site. OpenAI, injectable (classify() takes any LlmFn).
"""

from __future__ import annotations

import json
from typing import Any

_SYSTEM = (
    "You classify a B2B service firm's website as niched or generalist, for "
    "lead matching. The firm could be any kind of agency or professional-"
    "services provider (e.g. accounting/CPA, fractional-CFO, MSP, MSSP, cloud "
    "consulting). Your job is to extract the specific customer industries / "
    "verticals this business states it serves, in its own words on its own "
    "site — do NOT assume what the firm sells. Rules:\n"
    "1. If the site states the customer industries it serves outright (e.g. "
    "'we serve healthcare startups', an MSP saying 'IT support for law firms "
    "and dental practices', or a firm listing 'real estate investors, "
    "nonprofits, small businesses') -> niched, path='statement'. List EVERY "
    "served industry in `industries` as {phrase, guess}: phrase = their EXACT "
    "words copied verbatim from the page, guess = a one-word industry. Also "
    "set `focus`: 'single' if the site presents ONE clear dedicated industry "
    "focus, 'multiple' if it serves/lists several industries or client types. "
    "Keep niche_phrase/niche_guess set to the first/primary industry for "
    "compatibility.\n"
    "2. Else if a client list makes it obvious (2+ named clients in the same "
    "industry, all SMBs; ignore one-off or big-brand logos) -> niched, "
    "path='client_list', focus='single'. List the client names verbatim; put "
    "the industry in niche_guess.\n"
    "3. Anything else, including thin, parked, or unclassifiable sites -> "
    "generalist.\n"
    "4. SEPARATELY from the above (do this whether they are niched or "
    "generalist): if the site states the SIZE of client the firm works with in "
    "REVENUE terms — 'companies doing $1M-$10M', 'businesses with annual "
    "revenue below $50 million', 'clients from $2M to $50M' — copy that "
    "statement verbatim into `revenue_phrase`. Leave it EMPTY unless the "
    "figure describes the size of client they SERVE. A number about the firm "
    "itself is not this: 'clients supported (25+)', '$360M+ raised by our "
    "clients', 'we've saved clients $2M' are all about the firm's own track "
    "record, not the size of company it works with.\n"
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
        "Classify this firm by the customer industries it states it serves on "
        "its site. Return JSON with keys: classification "
        "('niched'|'generalist'), focus ('single'|'multiple'|''), path "
        "('statement'|'client_list'|''), industries (list of {phrase, guess}), "
        "niche_phrase, niche_guess, clients (list of {name}), revenue_phrase.\n\n"
        f"{pages}"
    )
    resp = client.chat.completions.create(
        model=model,
        temperature=0,                       # deterministic classification run-to-run
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
    )
    return json.loads(resp.choices[0].message.content or "{}")
