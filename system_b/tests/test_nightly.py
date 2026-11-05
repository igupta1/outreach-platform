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
