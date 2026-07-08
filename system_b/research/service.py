"""Orchestration: fetch a prospect's site, classify it, write the result to
the Airtable row. Network + Airtable live here so the classifier stays pure
and fully testable.
"""

from __future__ import annotations

from typing import Any

from system_b.research.classifier import LlmFn, classify
from system_b.research.fetcher import fetch_site
from system_b.research.llm import classify_site
from system_b.research.models import ResearchResult, to_airtable_fields


def research_prospect(
    website: str,
    taxonomy: dict[str, list[str]],
    *,
    llm: LlmFn | None = None,
) -> ResearchResult:
    """Fetch + classify one prospect's website. `llm` defaults to OpenAI;
    inject a fake in tests."""
    site = fetch_site(website)
    return classify(site, taxonomy, llm=llm or classify_site)


def research_and_write(
    record_id: str,
    website: str,
    taxonomy: dict[str, list[str]],
    airtable: Any,
    *,
    llm: LlmFn | None = None,
) -> ResearchResult:
    """Research a prospect and persist classification + evidence + match_param
    (+ niche_source, flags) to its Airtable row. Returns the result."""
    result = research_prospect(website, taxonomy, llm=llm)
    airtable.update(record_id, to_airtable_fields(result))
    return result
