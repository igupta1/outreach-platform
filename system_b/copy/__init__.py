"""Copy engine — Steps 4-5 of the spec.

ALL output is pure code — subject, framing, CTA, template, honesty, and every
per-lead line. No model writes any part of a sent email.
"""

from system_b.copy.email import EmailDraft, build_email_1
from system_b.copy.subject import build_subject

__all__ = [
    "build_subject",
    "build_email_1",
    "EmailDraft",
]
