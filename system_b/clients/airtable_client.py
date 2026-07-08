"""Airtable CRM: the Prospects table (one row per prospect) plus state
transitions. Schema is created programmatically via the Airtable Meta
API (needs schema.bases:write on the token); records use pyairtable.

Schema is exactly the M0 field list from the build plan.
"""

from __future__ import annotations

from typing import Any

import httpx
from pyairtable import Api

from system_b import config

_META_BASE = "https://api.airtable.com/v0/meta/bases"

# The full stage state machine (build plan / Part 5).
STAGES: list[str] = [
    "researched", "email_1_queued", "email_1_sent", "email_2_sent",
    "email_3_sent", "connect_sent", "connect_accepted", "dm_1_sent",
    "dm_2_sent", "replied", "call_booked", "closed", "do_not_contact",
]
REVIEW_STATUSES = ["pending", "approved", "edited", "rejected"]
GEO_LEVELS = ["city", "state", "none"]

_CHECKBOX = {"icon": "check", "color": "greenBright"}


def _select(choices: list[str]) -> dict[str, Any]:
    return {"choices": [{"name": c} for c in choices]}


# Field list for the Prospects table. The FIRST field is the primary
# field (must be text-like) — firm_name.
PROSPECT_FIELDS: list[dict[str, Any]] = [
    {"name": "firm_name", "type": "singleLineText"},
    {"name": "stage", "type": "singleSelect", "options": _select(STAGES)},
    {"name": "next_action", "type": "singleLineText"},
    {"name": "due_date", "type": "date", "options": {"dateFormat": {"name": "iso"}}},
    {"name": "city", "type": "singleLineText"},
    {"name": "state", "type": "singleLineText"},
    {"name": "email", "type": "email"},
    {"name": "linkedin", "type": "url"},
    {"name": "website", "type": "url"},
    {"name": "classification", "type": "singleSelect", "options": _select(["niched", "generalist"])},
    {"name": "match_param", "type": "singleLineText"},
    {"name": "niche_phrase", "type": "singleLineText"},
    {"name": "evidence", "type": "multilineText"},
    {"name": "all_niche", "type": "checkbox", "options": _CHECKBOX},
    {"name": "geo_level", "type": "singleSelect", "options": _select(GEO_LEVELS)},
    {"name": "sent_lead_ids", "type": "multilineText"},
    {"name": "flags", "type": "multilineText"},
    {"name": "message_history", "type": "multilineText"},
    {"name": "connection_accepted", "type": "checkbox", "options": _CHECKBOX},
    {"name": "review_status", "type": "singleSelect", "options": _select(REVIEW_STATUSES)},
    {"name": "queued_message", "type": "multilineText"},
]


class AirtableClient:
    def __init__(
        self,
        token: str | None = None,
        base_id: str | None = None,
        table_name: str | None = None,
    ) -> None:
        self.token = token or config.AIRTABLE_TOKEN
        self.base_id = base_id or config.AIRTABLE_BASE_ID
        self.table_name = table_name or config.AIRTABLE_TABLE_NAME
        if not (self.token and self.base_id):
            raise RuntimeError("AIRTABLE_TOKEN and AIRTABLE_BASE_ID are required")
        self._api = Api(self.token)
        self._http = httpx.Client(
            timeout=30.0,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )

    # --- Meta API (schema) -------------------------------------------------

    def _list_tables(self) -> list[dict[str, Any]]:
        r = self._http.get(f"{_META_BASE}/{self.base_id}/tables")
        r.raise_for_status()
        return r.json().get("tables", [])

    def _create_table(self) -> dict[str, Any]:
        body = {"name": self.table_name, "fields": PROSPECT_FIELDS}
        r = self._http.post(f"{_META_BASE}/{self.base_id}/tables", json=body)
        r.raise_for_status()
        return r.json()

    def _create_field(self, table_id: str, field: dict[str, Any]) -> None:
        r = self._http.post(
            f"{_META_BASE}/{self.base_id}/tables/{table_id}/fields", json=field
        )
        r.raise_for_status()

    def ensure_schema(self) -> dict[str, Any]:
        """Idempotent: create the Prospects table if missing, else add any
        missing fields. Returns a summary of what changed."""
        tables = self._list_tables()
        existing = next((t for t in tables if t["name"] == self.table_name), None)
        if existing is None:
            self._create_table()
            return {"created_table": True, "added_fields": [f["name"] for f in PROSPECT_FIELDS]}

        have = {f["name"] for f in existing.get("fields", [])}
        added: list[str] = []
        for field in PROSPECT_FIELDS:
            if field["name"] not in have:
                self._create_field(existing["id"], field)
                added.append(field["name"])
        return {"created_table": False, "added_fields": added}

    # --- Records -----------------------------------------------------------

    @property
    def table(self) -> Any:
        return self._api.table(self.base_id, self.table_name)

    def create_prospect(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.table.create(fields)

    def get(self, record_id: str) -> dict[str, Any]:
        return self.table.get(record_id)

    def update(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return self.table.update(record_id, fields)

    def set_stage(self, record_id: str, stage: str) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        return self.update(record_id, {"stage": stage})

    def find_by_firm(self, firm_name: str) -> dict[str, Any] | None:
        safe = firm_name.replace("'", "\\'")
        rows = self.table.all(formula=f"{{firm_name}} = '{safe}'", max_records=1)
        return rows[0] if rows else None

    def close(self) -> None:
        self._http.close()
