"""The nightly batch (system_b/nightly.py), the batch checks and the gate's
download record. Offline: no inventory, no model, no network."""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

from system_b import nightly
from system_b.review import checks
from system_b.review.serve import downloaded_path, load_packs, record_download


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["email", "first_seen"])
        w.writeheader()
        w.writerows(rows)


def _home(tmp_path: Path, batch: list[str], ledger: list[str]) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    (home / "system_b" / "data").mkdir(parents=True)
    _write_csv(home / "sequences.csv", [{"email": e, "subject": "s"} for e in batch])
    (home / "sequences.review.json").write_text(json.dumps(
        {"generated_at": "2026-11-04", "prospects": [{"email": e} for e in batch]}))
    ledger_path = home / "system_b" / "data" / "seen-prospects.csv"
    _write_csv(ledger_path, [{"email": e, "first_seen": "2026-11-04"} for e in ledger])
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    return home, ledger_path, downloads


def _ledger(path: Path) -> list[str]:
    with path.open(newline="") as fh:
        return [r["email"] for r in csv.DictReader(fh)]


def test_a_batch_never_downloaded_goes_back_on_the_queue(tmp_path):
    home, ledger, downloads = _home(tmp_path, ["a@x.com", "b@x.com"],
                                    ["old@x.com", "a@x.com", "b@x.com"])
    assert nightly.return_undownloaded(home, ledger, downloads) == (2, 0)
    assert _ledger(ledger) == ["old@x.com"]


def test_what_the_gate_recorded_or_downloads_hold_stays_sent(tmp_path):
    home, ledger, downloads = _home(tmp_path, ["a@x.com", "b@x.com", "c@x.com"],
                                    ["a@x.com", "b@x.com", "c@x.com"])
    record_download(home / "sequences.review.json", ["A@x.com"])
    time.sleep(0.01)
    _write_csv(downloads / "all-emails.csv", [{"email": "b@x.com", "subject": "s"}])
    assert nightly.return_undownloaded(home, ledger, downloads) == (1, 2)
    assert _ledger(ledger) == ["a@x.com", "b@x.com"]


def test_a_download_older_than_the_batch_does_not_count(tmp_path):
    home, ledger, downloads = _home(tmp_path, ["a@x.com"], ["a@x.com"])
    old = downloads / "all-emails.csv"
    _write_csv(old, [{"email": "a@x.com"}])
    past = (home / "sequences.csv").stat().st_mtime - 3600
    os.utime(old, (past, past))
    assert nightly.return_undownloaded(home, ledger, downloads) == (1, 0)


def test_the_previous_batch_is_archived_by_its_date(tmp_path):
    home, _, _ = _home(tmp_path, ["a@x.com"], [])
    record_download(home / "sequences.review.json", ["a@x.com"])
    assert nightly.archive_batch(home) == "2026-11-04"
    assert (home / "sequences-2026-11-04.csv").exists()
    assert (home / "sequences-2026-11-04.review.json").exists()
    assert (home / "sequences-2026-11-04.downloaded.json").exists()
    assert not (home / "sequences.csv").exists()
    _home(tmp_path / "again", ["b@x.com"], [])          # a second batch the same day
    second = tmp_path / "again" / "home"
    (second / "sequences-2026-11-04.csv").write_text("email\n")
    assert nightly.archive_batch(second) == "2026-11-04-2"


def test_the_download_record_is_a_union_beside_the_batch(tmp_path):
    review = tmp_path / "sequences.review.json"
    record_download(review, ["a@x.com", "B@x.com"])
    record_download(review, ["b@x.com", "c@x.com"])
    assert downloaded_path(review).name == "sequences.downloaded.json"
    assert json.loads(downloaded_path(review).read_text())["emails"] == [
        "a@x.com", "b@x.com", "c@x.com"]


def test_checks_reach_the_page(tmp_path):
    review = tmp_path / "sequences.review.json"
    review.write_text(json.dumps({"pack": "cfo", "prospects": [],
                                  "checks": {"items": [], "summary": {"fix": 0}}}))
    assert load_packs([review])["packs"][0]["checks"]["summary"] == {"fix": 0}


def _card(**kw):
    base = {"company": "Acme CPA", "email": "a@x.com", "first_name": "dana", "niche": "nonprofit",
            "subject": "3 denver nonprofits with audit problems", "gift_size": 3, "flags": [],
            "email_1_head": "hey dana,\n\nnoticed you work with nonprofits. these 3:\n\n"
                            "1. Hope House\n2. Mile High Youth\n3. Front Range Arts"}
    base.update(kw)
    return base


def test_a_clean_card_has_nothing_to_fix():
    assert checks.check_card(_card()) == []
    # "hey theresa," is a first name, not "hey there,"
    assert checks.check_card(_card(first_name="Theresa",
                                   email_1_head="hey theresa,\n\n1. Hope House")) == []


def test_the_checks_catch_what_the_hand_reviews_caught():
    head = ("hey there,\n\nsaw you work with $100m+ companies. here are 3 nonprofits:\n\n"
            "1. San Francisco Housing Accelerator Fund, The\n2. Childrens Initiative\n"
            "3. Rainwater, Holt & Sexton, P.A., little rock")
    found = {i["what"].split(":")[0] for i in checks.check_card(_card(
        niche=None, first_name="", email_1_head=head, gift_size=2,
        subject="3 texas food and beverage makers registered late for sales tax",
        flags=['name kept as the registry wrote it ("X P.C.")']))}
    assert {"no first name", "a name ends in \", The\"", "missing apostrophe",
            "legal form left in a lead name", "subject is 62 characters",
            "location-only email opens on client revenue; the leads are nonprofits, so cut that sentence",
            "fewer than 3 leads in the gift", "name kept as the registry wrote it (\"X P.C.\")"} <= found


def test_the_batch_summary_counts_matches():
    result = checks.check_batch({"prospects": [_card(), _card(niche=None, email="b@x.com")],
                                 "skipped": [["F", "no_gift"]]})
    assert result["summary"] == {"prospects": 2, "industry_match": 1, "location_only": 1,
                                 "no_gift": 1, "fix": 0, "look": 0}


def test_a_cut_off_name_or_a_dba_is_a_fix():
    items = checks.check_card(_card(
        email_1_head="hey dana,\n\n1. JRSK DBA Away\n2. Hope House\n3. Urban League of Greater",
        flags=['name cut off by the source (Urban League of Greater: "Greater") — check it']))
    whats = [i["what"] for i in items if i["kind"] == "fix"]
    assert any("DBA" in w for w in whats) and any("cut off" in w for w in whats)


# --- the run's status: retries and the line at the top of the gate ---------

from datetime import datetime as _dt

from system_b.review.serve import nightly_status


def test_a_retry_skips_a_night_already_built(tmp_path):
    home = tmp_path
    nightly.write_status(home, "ready", night="2026-11-06", started="2026-11-06T02:00:00")
    assert nightly.built_tonight(home, _dt(2026, 11, 6, 4, 0))
    assert not nightly.built_tonight(home, _dt(2026, 11, 7, 2, 0))       # a new night
    nightly.write_status(home, "failed", night="2026-11-06", started="2026-11-06T02:00:00")
    assert not nightly.built_tonight(home, _dt(2026, 11, 6, 4, 0))       # failed: try again


def test_the_next_try_follows_the_launchd_hours():
    assert nightly.next_try(_dt(2026, 11, 6, 2, 30)) == "4:00 am"
    assert nightly.next_try(_dt(2026, 11, 6, 4, 10)) == "6:00 am"
    assert nightly.next_try(_dt(2026, 11, 6, 6, 5)) is None


def _status(tmp_path, now, **st):
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "nightly-status.json").write_text(json.dumps(st))
    return nightly_status(logs, now)


def test_the_page_says_ready_with_the_build_time(tmp_path):
    line = _status(tmp_path, _dt(2026, 11, 6, 8, 0), state="ready", night="2026-11-06",
                   started="2026-11-06T02:00:05", finished="2026-11-06T03:50:40", emails=200, fix=2)
    assert line == {"kind": "ok", "text": "Ready · 200 emails · built 2:00–3:50 am · 2 to fix"}


def test_the_page_says_why_it_is_not_ready(tmp_path):
    failed = _status(tmp_path, _dt(2026, 11, 6, 3, 0), state="failed", night="2026-11-06",
                     started="2026-11-06T02:00:00", finished="2026-11-06T02:40:00",
                     reason="building the emails failed (exit 1)", next_try="4:00 am")
    assert failed["kind"] == "bad"
    assert failed["text"] == "Not ready: building the emails failed (exit 1) · next try 4:00 am"
    # yesterday's batch, after tonight's 02:00: the Mac slept through it
    stale = _status(tmp_path, _dt(2026, 11, 7, 8, 0), state="ready", night="2026-11-06",
                    started="2026-11-06T02:00:00", finished="2026-11-06T03:50:00", emails=200)
    assert stale["kind"] == "bad" and "This is the batch from Nov 6" in stale["text"]
    # ...but before 02:00 yesterday's batch is still the current one
    assert _status(tmp_path, _dt(2026, 11, 7, 1, 0), state="ready", night="2026-11-06",
                   started="2026-11-06T02:00:00", finished="2026-11-06T03:50:00",
                   emails=200)["kind"] == "ok"


def test_a_build_in_progress_or_one_that_died(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / ".nightly.lock").write_text(str(os.getpid()))
    running = _status(tmp_path, _dt(2026, 11, 6, 2, 30), state="building", night="2026-11-06",
                      started="2026-11-06T02:00:00")
    assert running == {"kind": "wait", "text": "Not ready yet: building now (started 2:00 am)"}
    (tmp_path / "logs" / ".nightly.lock").unlink()
    died = _status(tmp_path, _dt(2026, 11, 6, 3, 0), state="building", night="2026-11-06",
                   started="2026-11-06T02:00:00")
    assert died["kind"] == "bad" and "stopped partway" in died["text"]


def test_no_status_file_means_no_line(tmp_path):
    assert nightly_status(tmp_path) is None


def test_a_night_that_stops_records_why(tmp_path, monkeypatch):
    home, _, downloads = _home(tmp_path, [], [])
    monkeypatch.setattr(nightly, "refresh_running", lambda: True)
    monkeypatch.setattr(nightly.morning, "check", lambda: (["nonprofit: inventory file is not valid JSON"], []))
    monkeypatch.setattr(nightly.morning, "prospect_runway", lambda p, l: (900, 1500))
    assert nightly.main(["--home", str(home), "--downloads", str(downloads)]) == 1
    st = nightly.read_status(home)
    assert st["state"] == "failed" and st["reason"] == "nonprofit: inventory file is not valid JSON"
    assert "next_try" in st and st["night"] == _dt.now().date().isoformat()
