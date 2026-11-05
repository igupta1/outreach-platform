"""A refusal no retry fixes stops the batch (system_b/openai_client.py).
Offline: the responses are built by hand."""

from __future__ import annotations

import json

import httpx
import pytest

from system_b import openai_client
from system_b.openai_client import ModelUnavailable, check_response


def _resp(status: int, code: str | None = None) -> httpx.Response:
    body = json.dumps({"error": {"code": code, "message": "x"}}).encode() if code else b"{}"
    return httpx.Response(status, content=body, request=httpx.Request("POST", "https://api.openai.com/v1/x"))


def test_out_of_credits_stops_the_run():
    with pytest.raises(ModelUnavailable, match="out of credits"):
        check_response(_resp(429, "credit_balance_exhausted"))
    with pytest.raises(ModelUnavailable, match="out of credits"):
        check_response(_resp(429, "insufficient_quota"))
    with pytest.raises(ModelUnavailable, match="API key"):
        check_response(_resp(401, "invalid_api_key"))


def test_an_ordinary_rate_limit_or_error_does_not():
    check_response(_resp(429, "rate_limit_exceeded"))      # the client retries these
    check_response(_resp(500))
    check_response(_resp(200))


def test_the_fail_open_handlers_do_not_swallow_it():
    def fail_open_call():
        try:
            check_response(_resp(429, "credit_balance_exhausted"))
        except Exception:  # noqa: BLE001 -- the shape of every model call's guard
            return "kept as written"
    with pytest.raises(ModelUnavailable):
        fail_open_call()


def test_preflight_says_why(monkeypatch):
    class Dead:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise ModelUnavailable("OpenAI is out of credits: add credits")
    monkeypatch.setattr(openai_client, "client", lambda timeout=60: Dead)
    assert openai_client.preflight().startswith("OpenAI is out of credits")
