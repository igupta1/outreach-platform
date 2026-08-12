"""The dedup ledger + the CSV column contract.

The ledger exists so a run only ever processes prospects no earlier run has
sequenced — the filter runs before any site fetch or LLM call, so the review
gate holds exactly the sequences not yet seen. It is deliberately a flat email
list: it never learns who accepted or replied, because that record is
hand-maintained and a tool that rewrites a file a human has open eventually eats
a month of status.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from system_b.run import (
    COLUMNS,
    _append_ledger,
    _load_ledger,
    _review_path,
)

TODAY = date(2026, 8, 12)


def test_missing_ledger_reads_as_empty(tmp_path: Path):
    """First run ever: every prospect is new, and nothing raises."""
    assert _load_ledger(tmp_path / "nope.csv") == set()


def test_append_then_load_roundtrips(tmp_path: Path):
    led = tmp_path / "seen.csv"
    _append_ledger(led, ["a@x.com", "b@x.com"], TODAY)
    assert _load_ledger(led) == {"a@x.com", "b@x.com"}


def test_append_is_additive_and_never_rewrites(tmp_path: Path):
    """Two runs on different days accumulate; the first day's rows survive
    verbatim, including their original first_seen date."""
    led = tmp_path / "seen.csv"
    _append_ledger(led, ["a@x.com"], date(2026, 8, 10))
    _append_ledger(led, ["b@x.com"], date(2026, 8, 12))
    rows = list(csv.DictReader(led.open(newline="", encoding="utf-8")))
    assert [r["email"] for r in rows] == ["a@x.com", "b@x.com"]
    assert rows[0]["first_seen"] == "2026-08-10"     # untouched by the later run
    assert rows[1]["first_seen"] == "2026-08-12"


def test_append_writes_one_header_only(tmp_path: Path):
    led = tmp_path / "seen.csv"
    _append_ledger(led, ["a@x.com"], TODAY)
    _append_ledger(led, ["b@x.com"], TODAY)
    assert led.read_text(encoding="utf-8").count("first_seen") == 1


def test_append_of_nothing_creates_no_file(tmp_path: Path):
    """A run whose prospects were all seen before must not leave an empty
    ledger behind."""
    led = tmp_path / "seen.csv"
    _append_ledger(led, [], TODAY)
    assert not led.exists()


def test_dedup_is_case_insensitive_on_the_read_side(tmp_path: Path):
    led = tmp_path / "seen.csv"
    _append_ledger(led, ["paul@x.com"], TODAY)
    # run.py lowercases before comparing, so a differently-cased Apollo export
    # of the same person is still recognized
    assert "paul@x.com" in _load_ledger(led)
    assert "PAUL@x.com".lower() in _load_ledger(led)


def test_unreadable_ledger_degrades_to_empty(tmp_path: Path):
    """Dedup is an optimization. Losing it must never stop a run from writing
    its CSV, so a directory where a file belongs reads as 'nothing seen'."""
    led = tmp_path / "seen.csv"
    led.mkdir()
    assert _load_ledger(led) == set()


# --- path helpers ----------------------------------------------------------

def test_companion_paths_sit_next_to_the_out_csv():
    assert _review_path("out/cfo25.out.csv").name == "cfo25.out.review.json"
    # no suffix -> still appends rather than mangling the name
    assert _review_path("sequences").name == "sequences.review.json"


# --- the column contract ---------------------------------------------------

def test_csv_carries_both_channels_and_a_findable_name():
    """One row per prospect covering email AND LinkedIn, so the file the
    operator pastes into the history sheet is the same one Smartlead reads."""
    for col in ("pack", "cohort_date",
                "email", "first_name", "last_name", "company", "linkedin_url",
                "subject", "email_1", "email_2", "email_3",
                "li_dm_1", "li_dm_1_evergreen", "li_dm_2"):
        assert col in COLUMNS
    assert len(COLUMNS) == len(set(COLUMNS))


def test_history_header_starts_with_the_linkedin_columns():
    """The sheet is filled by PASTING the gate's LinkedIn CSV under the header,
    so those columns must be the leftmost ones, in exactly that order. The
    hand-kept status columns sit to their right, where a paste never lands."""
    from system_b.run import HISTORY_COLUMNS, LINKEDIN_COLUMNS

    assert HISTORY_COLUMNS[:len(LINKEDIN_COLUMNS)] == LINKEDIN_COLUMNS
    assert set(HISTORY_COLUMNS[len(LINKEDIN_COLUMNS):]) == {
        "connect_sent", "accepted", "dm1_sent", "dm2_sent",
        "replied_channel", "replied_date", "status",
    }


def test_history_sheet_carries_no_email_copy():
    """The email lives in the sequencer within the hour; the sheet exists for the
    LinkedIn lookup weeks later. Carrying both doubles its width for nothing."""
    from system_b.run import HISTORY_COLUMNS

    for col in ("subject", "email_1", "email_2", "email_3"):
        assert col not in HISTORY_COLUMNS


def _page_columns(name: str) -> list[str]:
    page = (Path(__file__).resolve().parent.parent / "review" / "page.html").read_text()
    m = re.search(rf"const {name} = \[(.*?)\];", page, re.S)
    assert m is not None, f"page.html no longer declares {name}"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_page_linkedin_export_matches_the_history_schema():
    """A drift here misaligns every future paste into the sheet."""
    from system_b.run import LINKEDIN_COLUMNS

    assert _page_columns("LINKEDIN_COLUMNS") == LINKEDIN_COLUMNS


def test_page_email_export_is_run_columns_minus_the_linkedin_ones():
    """The email CSV must stay a faithful subset of what run.py writes, or the
    file uploaded to the sequencer stops matching the run that produced it."""
    page_cols = _page_columns("EMAIL_COLUMNS")
    assert page_cols == [c for c in COLUMNS
                         if not c.startswith("li_") and c != "linkedin_url"]
