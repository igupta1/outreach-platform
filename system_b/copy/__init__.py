"""Copy engine — Steps 4-5 of the spec.

Structural output (subject, framing, CTA, template, honesty) is pure code;
the LLM fills only per-lead descriptions (copy.llm.describe_leads).
"""

from system_b.copy.email import EmailDraft, build_email_1, rotation_for
from system_b.copy.subject import build_subject

__all__ = [
    "build_subject",
    "build_email_1",
    "EmailDraft",
    "rotation_for",
]
