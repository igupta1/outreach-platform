"""The daily command's guards.

Both cases here are failures that LOOK like success. `pull` reports "kept
local copy" for a magnet that has not published yet, which is ordinary, so a
broken download hides inside a normal-looking line — and the freshness check
that would eventually catch it allows nonprofit inventory to be 400 days old.
"""

from __future__ import annotations

import json
from pathlib import Path

from system_b.morning import _lead_count


def _write(path: Path, n: int) -> Path:
    leads = [{"id": str(i), "name": f"org {i}"} for i in range(n)]
    path.write_text(json.dumps({"count": n, "leads": leads}))
    return path


def test_lead_count_reads_a_real_inventory(tmp_path):
    assert _lead_count(_write(tmp_path / "a.json", 359)) == 359


def test_lead_count_is_zero_for_anything_unusable(tmp_path):
    """Missing, empty, and malformed all have to read as zero — each one is a
    reason to keep what is already on disk, never to overwrite it."""
    assert _lead_count(tmp_path / "missing.json") == 0
    assert _lead_count(_write(tmp_path / "empty.json", 0)) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert _lead_count(bad) == 0


def test_an_empty_artifact_must_not_replace_a_populated_one(tmp_path):
    """This happened. The first funds run published 231 bytes of zero leads,
    before that workflow had a health check, and pulling it overwrote a good
    359-lead file. A download that destroys working data is worse than no
    download, so the comparison `have and not fresh` has to hold."""
    have = _lead_count(_write(tmp_path / "local.json", 359))
    fresh = _lead_count(_write(tmp_path / "artifact.json", 0))
    assert have and not fresh, "the keep-local branch would not fire"


def test_a_populated_artifact_does_replace_an_older_one(tmp_path):
    """The guard is only about EMPTY. A smaller-but-real refresh is still a
    refresh — the nonprofit magnet legitimately moved 3,984 -> 3,928 — and
    must not be mistaken for a failure."""
    have = _lead_count(_write(tmp_path / "local.json", 3984))
    fresh = _lead_count(_write(tmp_path / "artifact.json", 3928))
    assert not (have and not fresh)
