"""Track B — the sending layer.

`EmailSender` is the pluggable interface every upstream caller uses; nothing
outside this package talks to Smartlead directly (build-plan B1), so the
deliverability platform is swappable. `SmartleadSender` is the production
implementation; `FakeSender` records calls for offline tests.
"""

from __future__ import annotations

from system_b.sending.base import EmailSender, FakeSender, SentLead
from system_b.sending.smartlead import SmartleadError, SmartleadSender

__all__ = [
    "EmailSender",
    "FakeSender",
    "SentLead",
    "SmartleadSender",
    "SmartleadError",
]
