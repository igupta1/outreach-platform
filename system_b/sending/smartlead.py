"""B1 — the Smartlead implementation of `EmailSender`.

Smartlead REST API (base https://server.smartlead.ai/api/v1, auth via an
`api_key` query param). Endpoints used:
  * POST /campaigns/{cid}/leads                    — add a lead (custom_fields)
  * POST /campaigns/{cid}/leads/{lid}              — update a lead's custom_fields
  * POST /campaigns/{cid}/leads/{lid}/pause        — freeze a lead
  * POST /campaigns/{cid}/leads/{lid}/resume       — un-freeze
  * GET  /leads/?email=                            — resolve a lead id by email
  * POST /campaigns/{cid}/sequences                — save the 3-step sequence (A6)
  * POST /campaigns/{cid}/webhooks                 — register the reply webhook
  * POST /campaigns                                — create a campaign

The per-lead {{subject}} / {{email_1..3}} variables are Smartlead custom
fields; the campaign sequence (save_sequence) references them. Plain-text copy
is converted to minimal HTML (newlines -> <br>) so it renders as written.
"""

from __future__ import annotations

import html
from typing import Any

import httpx

from system_b import config
from system_b.sending.base import EmailSender


class SmartleadError(RuntimeError):
    """A non-2xx Smartlead response (carries status + body for debugging)."""


def _plain_to_html(text: str) -> str:
    """Minimal, safe HTML so line breaks survive Smartlead's HTML body.

    Each newline becomes a single <br> with NO trailing "\n": Smartlead runs its
    own newline->line-break pass over the body, so leaving the raw "\n" in place
    doubles every break (visibly spaced-out emails)."""
    return html.escape(text).replace("\r\n", "\n").replace("\n", "<br>")


class SmartleadSender(EmailSender):
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or config.SMARTLEAD_API_KEY
        if not self.api_key:
            raise RuntimeError("SMARTLEAD_API_KEY is required for SmartleadSender")
        self.base_url = (base_url or config.SMARTLEAD_BASE_URL).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s)

    # --- low-level ---------------------------------------------------------

    def _request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        params = {**(params or {}), "api_key": self.api_key}
        resp = self._client.request(method, f"{self.base_url}{path}", json=json, params=params)
        if resp.status_code >= 400:
            raise SmartleadError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # --- EmailSender ------------------------------------------------------

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
        custom_fields = {
            "subject": subject,
            "email_1": _plain_to_html(email_1),
            **(extra_fields or {}),
        }
        lead: dict[str, Any] = {"email": email, "custom_fields": custom_fields}
        if first_name:
            lead["first_name"] = first_name
        body = {
            "lead_list": [lead],
            # Add the lead even if it already exists in ANOTHER campaign
            # (ignore_duplicate_leads_in_other_campaign=False). With True, Smartlead
            # SKIPS the add, yet find_lead_id below still resolves the global id —
            # reporting a false "sent" for a lead that never entered this campaign.
            "settings": {"ignore_global_block_list": False,
                         "ignore_unsubscribe_list": False,
                         "ignore_duplicate_leads_in_other_campaign": False},
        }
        resp = self._request("POST", f"/campaigns/{campaign_id}/leads", json=body)
        # Surface a silent skip (block list, unsubscribe, ...) as an error instead
        # of a false success: find_lead_id is a GLOBAL lookup, so it would resolve
        # an id even for a lead Smartlead never added to THIS campaign.
        if isinstance(resp, dict) and "upload_count" in resp:
            added = int(resp.get("upload_count") or 0) + int(resp.get("already_added_to_campaign") or 0)
            if added < 1:
                raise SmartleadError(
                    f"lead {email} was not added to campaign {campaign_id} (upload skipped): {resp}"
                )
        # The add response doesn't reliably carry the lead id — resolve it.
        lead_id = self.find_lead_id(campaign_id, email)
        if not lead_id:
            raise SmartleadError(f"added {email} but could not resolve its lead id")
        return lead_id

    def set_followup(self, campaign_id: str, lead_id: str, *, step: int, body: str, email: str) -> None:
        field = f"email_{step}"
        # Smartlead's update-lead endpoint requires `email` in the body even when
        # only updating custom_fields.
        self._request(
            "POST", f"/campaigns/{campaign_id}/leads/{lead_id}",
            json={"email": email, "custom_fields": {field: _plain_to_html(body)}},
        )

    def pause_lead(self, campaign_id: str, lead_id: str) -> None:
        self._request("POST", f"/campaigns/{campaign_id}/leads/{lead_id}/pause")

    def resume_lead(self, campaign_id: str, lead_id: str) -> None:
        self._request("POST", f"/campaigns/{campaign_id}/leads/{lead_id}/resume")

    def find_lead_id(self, campaign_id: str, email: str) -> str | None:
        data = self._request("GET", "/leads/", params={"email": email})
        if isinstance(data, dict):
            lid = data.get("id") or (data.get("lead") or {}).get("id")
            return str(lid) if lid is not None else None
        if isinstance(data, list) and data:
            lid = data[0].get("id")
            return str(lid) if lid is not None else None
        return None

    # --- one-time campaign setup (A6) -------------------------------------

    def create_campaign(self, name: str) -> str:
        data = self._request("POST", "/campaigns/create", json={"name": name, "client_id": None})
        cid = (data or {}).get("id") if isinstance(data, dict) else None
        if cid is None:
            raise SmartleadError(f"create_campaign({name!r}) returned no id: {data}")
        return str(cid)

    def attach_mailboxes(self, campaign_id: str, email_account_ids: list[int]) -> Any:
        return self._request(
            "POST", f"/campaigns/{campaign_id}/email-accounts",
            json={"email_account_ids": email_account_ids},
        )

    def set_schedule(self, campaign_id: str, schedule: dict[str, Any]) -> Any:
        # Smartlead's schedule update is a POST (the live API 404s on PATCH).
        return self._request("POST", f"/campaigns/{campaign_id}/schedule", json=schedule)

    def save_sequence(self, campaign_id: str, gaps: dict[int, int] | None = None) -> None:
        """Save the 3-step threaded sequence (A6). Step 1 carries the subject +
        {{email_1}}; steps 2-3 are blank-subject (thread) with {{email_2/3}}."""
        gaps = gaps or config.SEQUENCE_STEP_GAP_DAYS
        seq = [
            {"seq_number": 1, "seq_delay_details": {"delay_in_days": gaps.get(1, 0)},
             "subject": "{{subject}}", "email_body": "{{email_1}}"},
            {"seq_number": 2, "seq_delay_details": {"delay_in_days": gaps.get(2, 3)},
             "subject": "", "email_body": "{{email_2}}"},
            {"seq_number": 3, "seq_delay_details": {"delay_in_days": gaps.get(3, 4)},
             "subject": "", "email_body": "{{email_3}}"},
        ]
        self._request("POST", f"/campaigns/{campaign_id}/sequences", json={"sequences": seq})

    # Smartlead requires a non-empty `categories` filter; these are the standard
    # master lead categories — all of them, so the reply webhook fires on ANY
    # reply regardless of how Smartlead classifies it.
    ALL_REPLY_CATEGORIES = [
        "Interested", "Meeting Request", "Not Interested", "Do Not Contact",
        "Information Request", "Out Of Office", "Wrong Person",
    ]

    def register_reply_webhook(
        self, campaign_id: str, webhook_url: str, *, name: str = "reply-freeze",
        event_types: list[str] | None = None, categories: list[str] | None = None,
    ) -> Any:
        """Register the EMAIL_REPLY (+ unsubscribe) webhook that B5 receives."""
        return self._request(
            "POST", f"/campaigns/{campaign_id}/webhooks",
            json={
                "name": name,
                "webhook_url": webhook_url,
                "event_types": event_types or ["EMAIL_REPLY", "LEAD_UNSUBSCRIBED"],
                "categories": categories or self.ALL_REPLY_CATEGORIES,
            },
        )

    def close(self) -> None:
        self._client.close()
