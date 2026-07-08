"""Prospect research — Step 2a (classify niched vs generalist with evidence).

The honesty rule is enforced in code: every saved fact appears word-for-word
on the prospect's site (classifier.appears_verbatim / evidence_covers), so a
fact can never reach an email unless the site backs it up.
"""

from system_b.research.classifier import appears_verbatim, classify, evidence_covers
from system_b.research.models import Evidence, ResearchResult, to_airtable_fields
from system_b.research.service import research_and_write, research_prospect

__all__ = [
    "classify",
    "appears_verbatim",
    "evidence_covers",
    "Evidence",
    "ResearchResult",
    "to_airtable_fields",
    "research_prospect",
    "research_and_write",
]
