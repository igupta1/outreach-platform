"""The OpenAI client every model call in a batch uses: one that STOPS the run
when OpenAI refuses for a reason no retry fixes (no credits, a bad key).

Every model call here fails open on purpose (a name fixer that errors keeps the
name as written; a claim check that errors says "no"), which is right for one
flaky call and wrong for all of them. 2026-11-05: the credits ran out 182
firms into the nightly batch, and the run went on through the other 900,
quietly turning firms with a niche into location-only drafts. So a refusal
like that raises `ModelUnavailable`, a BaseException: it passes through the
`except Exception` around each call, `run.py` stops before writing the batch
or the ledger, and the gate's status line says what to do.
"""

from __future__ import annotations

import json
from typing import Any

# OpenAI's error codes for "this account cannot make calls right now".
FATAL_CODES = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
               "invalid_api_key", "account_deactivated"}
EXIT_CODE = 3        # run.py's exit status for it; system_b.nightly reads it


class ModelUnavailable(BaseException):
    """OpenAI will not answer until a person fixes the account."""


def _code(body: bytes) -> str:
    try:
        err = json.loads(body or b"{}").get("error") or {}
    except ValueError:
        return ""
    return str(err.get("code") or err.get("type") or "")


def check_response(response: Any) -> None:
    """httpx response hook: raise on a refusal no retry fixes."""
    if response.status_code not in (401, 403, 429):
        return
    response.read()
    code = _code(response.content)
    if response.status_code == 401 or code in FATAL_CODES:
        raise ModelUnavailable(
            "OpenAI is out of credits: add credits at "
            "platform.openai.com/settings/organization/billing"
            if code in {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached"}
            else f"OpenAI refused the API key ({code or response.status_code})")


def client(timeout: float = 60) -> Any:
    from openai import DefaultHttpxClient, OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    return OpenAI(api_key=config.OPENAI_API_KEY, timeout=timeout,
                  http_client=DefaultHttpxClient(event_hooks={"response": [check_response]}))


def preflight() -> str | None:
    """One tiny call before a batch: None when OpenAI answers, else why not."""
    try:
        client(timeout=30).chat.completions.create(
            model="gpt-4o-mini", max_tokens=1, messages=[{"role": "user", "content": "ok"}])
    except ModelUnavailable as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 -- network etc.: worth a retry, not a stop
        return f"OpenAI did not answer ({type(exc).__name__})"
    return None
