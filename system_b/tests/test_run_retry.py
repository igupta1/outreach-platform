"""A dropped connection to the model retries the firm; other errors do not."""

import pytest

from system_b.run import with_retry


class APIConnectionError(Exception):
    pass


def test_dropped_connection_is_retried():
    calls, slept = [], []

    def call():
        calls.append(1)
        if len(calls) < 3:
            raise APIConnectionError("Connection error.")
        return {"status": "ok"}

    assert with_retry(call, "Acme", sleep=slept.append) == {"status": "ok"}
    assert len(calls) == 3 and slept == [5, 30]


def test_gives_up_after_the_last_pause():
    def call():
        raise APIConnectionError("Connection error.")

    with pytest.raises(APIConnectionError):
        with_retry(call, "Acme", sleep=lambda s: None)


def test_other_errors_fail_at_once():
    calls = []

    def call():
        calls.append(1)
        raise ValueError("a bug")

    with pytest.raises(ValueError):
        with_retry(call, "Acme", sleep=lambda s: None)
    assert len(calls) == 1
