"""The advisory copy read — and the guards that keep it advisory.

The model is never given the pen here. It returns spans it thinks read as
machine-written; code keeps only spans that are really in the copy, caps them,
and swallows every failure. Nothing it returns can change a sent email.
"""

from __future__ import annotations

from system_b.copy.naturalness import _MAX_ISSUES, _verified, check_naturalness

TEXT = (
    "hey paul,\n\n"
    "noticed you work with nonprofits, so i pulled 3 more:\n\n"
    "1. Antilles Power Depot, Inc., denver: is looking for a chief financial officer\n"
)


def test_a_quote_that_is_not_in_the_copy_is_dropped():
    """The verbatim test is what makes a suggestion safe to show: an operator who
    reads "this sounds off" and cannot find the phrase has been sent chasing a
    hallucination."""
    issues = _verified(
        [
            {"quote": "Antilles Power Depot, Inc.", "why": "reads like a filing"},
            {"quote": "a phrase that was never written", "why": "invented"},
        ],
        TEXT,
    )
    assert [i["quote"] for i in issues] == ["Antilles Power Depot, Inc."]


def test_issues_are_capped():
    """One talkative response must not turn a clean card into a wall of advice,
    which would bury the honesty flags that actually stop a send."""
    many = [{"quote": w, "why": "x"} for w in TEXT.split() if len(w) > 3]
    assert len(many) > _MAX_ISSUES
    assert len(_verified(many, TEXT)) == _MAX_ISSUES


def test_duplicate_quotes_collapse():
    issues = _verified(
        [{"quote": "nonprofits", "why": "a"}, {"quote": "nonprofits", "why": "b"}],
        TEXT,
    )
    assert len(issues) == 1


def test_malformed_entries_are_ignored_not_crashed_on():
    issues = _verified(
        ["a bare string", None, 42, {"no_quote": "x"}, {"quote": "", "why": "y"},
         {"quote": "nonprofits", "why": "ok"}],
        TEXT,
    )
    assert issues == [{"quote": "nonprofits", "why": "ok"}]


def test_missing_why_still_yields_a_usable_issue():
    assert _verified([{"quote": "nonprofits"}], TEXT) == [{"quote": "nonprofits", "why": ""}]


def test_empty_text_never_calls_the_model():
    """Guards the no-copy case before any client is constructed, so it also
    cannot raise on a missing API key."""
    assert check_naturalness("") == []
    assert check_naturalness("   ") == []


def test_a_provider_failure_is_swallowed(monkeypatch):
    """An advisory read is not worth failing a run over. A missing suggestion
    costs nothing the operator's own eyes do not already cover."""
    import system_b.config as config

    monkeypatch.setattr(config, "OPENAI_API_KEY", "", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert check_naturalness(TEXT) == []


def test_the_check_is_optional_at_the_sequence_level():
    """`generate_sequence(naturalness=None)` produces no suggestions and makes no
    call — which is what `--skip-naturalness` relies on."""
    import inspect

    from system_b.sequence.generate import generate_sequence

    sig = inspect.signature(generate_sequence)
    assert sig.parameters["naturalness"].default is None
