"""B1 — the `EmailSender` interface + a `FakeSender` test double.

Model (build-plan B1): one prospect = one lead in a threaded campaign.
  * First touch  -> `add_lead` sets the {{subject}} / {{email_1}} variables.
  * Follow-up    -> `set_followup` UPDATES that same lead's {{email_2}} /
    {{email_3}} variable (same inbox, same thread) — it is NOT a new send;
    Smartlead's step timer sends it.
  * Reply / opt-out -> `pause_lead` freezes every remaining step for that lead.

Everything above the sender speaks only these methods, so Smartlead can be
swapped for another platform by writing one more subclass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SentLead:
    """A record of a first-touch push (what the caller stores back on the row)."""
    campaign_id: str
    lead_id: str
    email: str


class EmailSender(ABC):
    """Pluggable outbound-email platform. Campaign ids are opaque strings."""

    @abstractmethod
    def add_lead(
        self,
        campaign_id: str,
        *,
        email: str,
        first_name: str | None,
        subject: str,
        email_1: str,
        extra_fields: dict[str, str] | None = None,
    ) -> str:
        """Add the prospect as a lead with Email #1 populated. Returns the
        platform lead id (used for follow-up updates / pause)."""

    @abstractmethod
    def set_followup(self, campaign_id: str, lead_id: str, *, step: int, body: str, email: str) -> None:
        """Populate the {{email_2}} / {{email_3}} variable for an existing lead
        BEFORE its step timer fires (build-plan B3/B5 timing guard). Smartlead's
        update-lead endpoint requires the lead's email in the body."""

    @abstractmethod
    def pause_lead(self, campaign_id: str, lead_id: str) -> None:
        """Freeze all remaining steps for this lead (reply / opt-out / guard)."""

    @abstractmethod
    def resume_lead(self, campaign_id: str, lead_id: str) -> None:
        """Un-freeze a previously paused lead."""

    def find_lead_id(self, campaign_id: str, email: str) -> str | None:  # pragma: no cover
        """Look up the platform lead id for an email (fallback when add_lead's
        response doesn't carry it). Optional per backend."""
        return None


class FakeSender(EmailSender):
    """In-memory test double: records every call, hands out deterministic ids.
    No network. Used by the offline test suite and dry-run scripts."""

    def __init__(self) -> None:
        self.added: list[dict[str, str]] = []
        self.followups: list[dict[str, object]] = []
        self.paused: list[tuple[str, str]] = []
        self.resumed: list[tuple[str, str]] = []
        self._by_email: dict[str, str] = {}
        self._n = 0

    def add_lead(
        self,
        campaign_id: str,
        *,
        email: str,
        first_name: str | None,
        subject: str,
        email_1: str,
        extra_fields: dict[str, str] | None = None,
    ) -> str:
        self._n += 1
        lead_id = f"fake-lead-{self._n}"
        self.added.append({
            "campaign_id": campaign_id, "lead_id": lead_id, "email": email,
            "first_name": first_name or "", "subject": subject, "email_1": email_1,
        })
        self._by_email[email.lower()] = lead_id
        return lead_id

    def set_followup(self, campaign_id: str, lead_id: str, *, step: int, body: str, email: str = "") -> None:
        self.followups.append(
            {"campaign_id": campaign_id, "lead_id": lead_id, "step": step, "body": body, "email": email}
        )

    def pause_lead(self, campaign_id: str, lead_id: str) -> None:
        self.paused.append((campaign_id, lead_id))

    def resume_lead(self, campaign_id: str, lead_id: str) -> None:
        self.resumed.append((campaign_id, lead_id))

    def find_lead_id(self, campaign_id: str, email: str) -> str | None:
        return self._by_email.get(email.lower())
