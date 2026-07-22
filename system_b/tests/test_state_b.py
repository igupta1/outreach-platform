"""B2 — the extended sequence state machine transitions."""

from __future__ import annotations

import pytest

from system_b.clients.airtable_client import STAGES
from system_b.review.state import (
    APPROVE_ADVANCE,
    is_terminal,
    mark_do_not_contact,
    mark_replied,
    stage_after_send,
)


class FakeAirtable:
    def __init__(self):
        self.records: dict[str, dict] = {}

    def update(self, rid, fields):
        self.records.setdefault(rid, {}).update(fields)
        return {"id": rid, "fields": self.records[rid]}

    def set_stage(self, rid, stage):
        assert stage in STAGES
        return self.update(rid, {"stage": stage})


def test_stage_after_send_maps_all_three_steps():
    assert stage_after_send(1) == "email_1_sent"
    assert stage_after_send(2) == "email_2_sent"
    assert stage_after_send(3) == "email_3_sent"
    with pytest.raises(ValueError):
        stage_after_send(4)


def test_approve_advance_covers_followups():
    assert APPROVE_ADVANCE["researched"] == "email_1_queued"
    assert APPROVE_ADVANCE["email_1_sent"] == "email_2_sent"
    assert APPROVE_ADVANCE["email_2_sent"] == "email_3_sent"


def test_terminal_stages():
    assert is_terminal("replied") and is_terminal("do_not_contact")
    assert not is_terminal("email_1_sent")


def test_mark_replied_freezes_and_records():
    at = FakeAirtable()
    mark_replied(at, "r1", reply_body="thanks, interested", replied_at="2026-07-11")
    f = at.records["r1"]
    assert f["stage"] == "replied" and f["frozen"] is True
    assert f["last_reply"] == "thanks, interested" and f["replied_at"] == "2026-07-11"


def test_mark_do_not_contact_freezes():
    at = FakeAirtable()
    mark_do_not_contact(at, "r2", reason="unsubscribed")
    f = at.records["r2"]
    assert f["stage"] == "do_not_contact" and f["frozen"] is True
