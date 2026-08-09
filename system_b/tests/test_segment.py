"""Segment-level market context (copy/segment.py) — the step-2 follow-up's
different KIND of value, and the honesty rules around stating a count.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_segment.py -q
"""

from __future__ import annotations

from datetime import date

from system_b.copy.segment import segment_line
from system_b.models import Lead, Signal

TODAY = date(2026, 8, 9)


def mk(id: str, *, state: str, days_ago: int = 3,
       headcount: int | None = None, band: str | None = "11-50") -> Lead:
    d = date.fromordinal(TODAY.toordinal() - days_ago).isoformat()
    return Lead(
        id=id, company=id, state=state, signal_type="job_finance_lead",
        headcount=headcount, headcount_band=band,
        signals=[Signal(type="job_finance_lead", date=d, date_confidence="high")],
    )


def test_counts_only_the_prospects_state():
    leads = [mk(f"g{i}", state="GA") for i in range(6)] + \
            [mk(f"t{i}", state="TX") for i in range(9)]
    line = segment_line(leads, state="GA", today=TODAY, label="georgia")
    assert line.startswith("6 came through in georgia this month")


def test_says_came_through_not_were_posted():
    """The inventory is a SAMPLE of the market, never the whole of it. 'came
    through' reports what this feed saw; 'were posted' would claim a market
    total we cannot support."""
    line = segment_line([mk(f"g{i}", state="GA") for i in range(8)],
                        state="GA", today=TODAY, label="georgia")
    assert "came through" in line
    assert "were posted" not in line and "companies in georgia posted" not in line


def test_thin_segment_is_omitted_entirely():
    """'1 came through in wyoming this month' is worse than saying nothing."""
    for n in range(0, 5):
        leads = [mk(f"w{i}", state="WY") for i in range(n)]
        assert segment_line(leads, state="WY", today=TODAY, label="wyoming") == ""
    leads = [mk(f"w{i}", state="WY") for i in range(5)]
    assert segment_line(leads, state="WY", today=TODAY, label="wyoming") != ""


def test_stale_leads_fall_out_of_the_window():
    fresh = [mk(f"f{i}", state="GA", days_ago=5) for i in range(5)]
    old = [mk(f"o{i}", state="GA", days_ago=90) for i in range(20)]
    line = segment_line(fresh + old, state="GA", today=TODAY, label="georgia")
    assert line.startswith("5 came through")     # the 20 stale ones are excluded


def test_size_split_uses_the_band_when_the_exact_count_is_missing():
    # ~98% of leads carry a band and only ~47% an exact count, so counting on
    # the exact number would silently describe half the segment.
    leads = [mk(f"s{i}", state="GA", headcount=None, band="11-50") for i in range(6)]
    line = segment_line(leads, state="GA", today=TODAY, label="georgia")
    assert line == "6 came through in georgia this month, 6 at companies under 50 people."


def test_exact_count_wins_over_the_band_and_unsized_never_inflates():
    leads = [
        mk("a", state="GA", headcount=12, band="51-200"),   # exact says small
        mk("b", state="GA", headcount=800, band="11-50"),   # exact says big
        mk("c", state="GA", headcount=None, band="1-10"),   # band says small
        mk("d", state="GA", headcount=None, band=None),     # unknown -> not counted
        mk("e", state="GA", headcount=None, band="51-200"),
        mk("f", state="GA", headcount=None, band="11-50"),
    ]
    line = segment_line(leads, state="GA", today=TODAY, label="georgia")
    assert line == "6 came through in georgia this month, 3 at companies under 50 people."


def test_no_state_means_no_line():
    leads = [mk(f"g{i}", state="GA") for i in range(9)]
    assert segment_line(leads, state=None, today=TODAY, label="georgia") == ""
    assert segment_line(leads, state="GA", today=TODAY, label="") == ""


def test_drops_the_size_clause_when_none_are_provably_small():
    leads = [mk(f"b{i}", state="GA", headcount=None, band="51-200") for i in range(7)]
    line = segment_line(leads, state="GA", today=TODAY, label="georgia")
    assert line == "7 came through in georgia this month."


def test_state_formats_are_normalized_before_comparing():
    """Apollo gives the prospect "Georgia"; leadgen gives the lead "GA". A raw
    string compare matches nothing and the feature dies silently — every segment
    reads as empty. Both sides must normalize."""
    leads = [mk(f"g{i}", state="GA") for i in range(7)]
    for prospect_state in ("Georgia", "GA", "georgia", " ga "):
        line = segment_line(leads, state=prospect_state, today=TODAY, label="georgia")
        assert line.startswith("7 came through in georgia"), prospect_state
    # and the reverse: full-name leads against a 2-letter prospect state
    full = [mk(f"f{i}", state="Georgia") for i in range(7)]
    assert segment_line(full, state="GA", today=TODAY, label="georgia").startswith("7 came through")
