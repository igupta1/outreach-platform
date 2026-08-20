"""The cross-pack LinkedIn connection queue.

The LinkedIn cap is one budget across every campaign, not one per pack, so the
day's list has to be merged and ranked once.

Run:  system_b/.venv/bin/python -m pytest system_b/tests/test_connect_queue.py -q
"""

from __future__ import annotations

import json

from system_b.connect_queue import COLUMNS, build_queue, load_reviews, main


def P(company, rank, *, linkedin="https://linkedin.com/in/x", label="niche", **kw):
    return {
        "company": company, "first_name": kw.get("first_name", "sam"),
        "last_name": kw.get("last_name", "lee"), "email": kw.get("email", "s@x.com"),
        "city": kw.get("city", "denver"), "state": kw.get("state", "CO"),
        "linkedin": linkedin,
        "personalization": {"rank": rank, "label": label},
    }


def _write(tmp_path, name, pack, prospects):
    path = tmp_path / name
    path.write_text(json.dumps({"pack": pack, "prospects": prospects}), encoding="utf-8")
    return path


def test_the_best_prospects_win_regardless_of_pack(tmp_path):
    """The whole point: three packs, one cap. A rank-1 bookkeeping prospect
    outranks a rank-5 cfo one, which working three files down separately would
    never surface."""
    a = _write(tmp_path, "cfo.json", "cfo", [P("Cfo Weak", 5), P("Cfo Mid", 3)])
    b = _write(tmp_path, "book.json", "bookkeeping", [P("Book Strong", 1)])
    rows = build_queue(load_reviews([a, b]), top=3)
    assert [r["company"] for r in rows] == ["Book Strong", "Cfo Mid", "Cfo Weak"]
    assert [r["pack"] for r in rows] == ["bookkeeping", "cfo", "cfo"]
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_prospects_with_no_linkedin_are_dropped_before_the_cut(tmp_path):
    """A queue of 20 must be 20 people you can actually act on, not 20 rows of
    which some are dead."""
    a = _write(tmp_path, "a.json", "cfo", [
        P("No Link", 1, linkedin=""), P("Blank Link", 1, linkedin="   "), P("Real", 4),
    ])
    rows = build_queue(load_reviews([a]), top=20)
    assert [r["company"] for r in rows] == ["Real"]


def test_company_breaks_ties_so_the_order_is_stable(tmp_path):
    a = _write(tmp_path, "a.json", "cfo", [P("Zeta", 2), P("Alpha", 2), P("Mid", 2)])
    rows = build_queue(load_reviews([a]), top=10)
    assert [r["company"] for r in rows] == ["Alpha", "Mid", "Zeta"]


def test_unranked_prospects_sort_last(tmp_path):
    a = _write(tmp_path, "a.json", "cfo", [{"company": "No Rank",
                                            "linkedin": "https://l/x"}, P("Ranked", 6)])
    rows = build_queue(load_reviews([a]), top=10)
    assert [r["company"] for r in rows] == ["Ranked", "No Rank"]


def test_top_caps_the_list(tmp_path):
    a = _write(tmp_path, "a.json", "cfo", [P(f"C{i}", i) for i in range(1, 9)])
    assert len(build_queue(load_reviews([a]), top=3)) == 3


def test_an_unreadable_file_does_not_cost_the_rest_of_the_day(tmp_path):
    good = _write(tmp_path, "good.json", "cfo", [P("Good Co", 1)])
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    missing = tmp_path / "nope.json"
    rows = build_queue(load_reviews([good, bad, missing]), top=10)
    assert [r["company"] for r in rows] == ["Good Co"]


def test_cli_writes_the_csv(tmp_path, capsys):
    a = _write(tmp_path, "a.json", "cfo", [P("Acme", 1)])
    b = _write(tmp_path, "b.json", "accounting", [P("Beta", 2)])
    out = tmp_path / "queue.csv"
    assert main([str(a), str(b), "--top", "20", "--out", str(out)]) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(COLUMNS)
    assert len(lines) == 3
    assert "Acme" in lines[1] and "Beta" in lines[2]


def test_cli_reports_when_there_is_nothing_to_do(tmp_path, capsys):
    empty = _write(tmp_path, "e.json", "cfo", [])
    assert main([str(empty), "--out", str(tmp_path / "q.csv")]) == 1
