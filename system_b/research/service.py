"""Orchestration: fetch a prospect's site and classify it. Network lives here so
the classifier stays pure and fully testable.
"""

from __future__ import annotations

from system_b.research.classifier import LlmFn, classify
from system_b.research.fetcher import fetch_site
from system_b.research.llm import classify_site, client_names_fit
from system_b.research.models import ResearchResult


def research_prospect(
    website: str,
    taxonomy: dict[str, list[str]],
    *,
    llm: LlmFn | None = None,
) -> ResearchResult:
    """Fetch + classify one prospect's website. `llm` defaults to OpenAI;
    inject a fake in tests. The client-list check (`client_names_fit`) runs
    only with the real classifier, so a test's fake never reaches the network."""
    site = fetch_site(website)
    return classify(site, taxonomy, llm=llm or classify_site,
                    client_fit=client_names_fit if llm is None else None)
