"""The nightly batch: yesterday's leftovers back, today's 200 built and checked.

    system_b/.venv/bin/python -m system_b.nightly --home ~/Developer/outreach-platform

Run by `ops/nightly.sh` at 02:00 Pacific (launchd, `ops/com.outreach.nightly.plist`)
from a checkout of the last pushed, tested commit, so a half-finished edit in
the working tree can never break a night. The user's ask (2026-11-04): open
the review gate in the morning and find it ready, with anything to fix listed.

    1. RETURN   prospects of the previous batch that were never downloaded go
                back on the queue (off the ledger), so a skipped day costs
                nothing. "Downloaded" = the gate recorded the download
                (`<batch>.downloaded.json`) OR a downloaded CSV in ~/Downloads
                carries the address. Only an address with NEITHER goes back:
                emailing someone twice is worse than losing a draft.
    2. ARCHIVE  the previous batch to sequences-<date>.*
    3. PUBLISH  the inventory (skipped while its weekly refresh holds the lock;
                the files on disk are a week old at most)
    4. CHECK    `morning.check`: a blocking problem stops the night
    5. GENERATE `run.py --target 200` into sequences.csv
    6. REVIEW   `review.checks` stored in the review JSON (the gate lists them
                at the top), and a one-screen summary in logs/nightly-latest.txt

Every run records how it went in logs/nightly-status.json (building / ready /
failed, with the reason); the review gate shows it as one line at the top.
launchd starts the job at 02:00, 04:00 and 06:00: the later two are retries
and exit at once when tonight's batch is already built (`--built-tonight`).

Nothing is sent. The batch goes to Smartlead only when the user downloads it.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from system_b import morning
from system_b.review import checks

TARGET = 200
# Below this many unsent prospects the summary says to pull a new Apollo list:
# three nights of runway.
LOW_RUNWAY = 600
# launchd's start hours (ops/com.outreach.nightly.plist): the first run, then
# two retries for a night that failed.
RUN_HOURS = (2, 4, 6)
BATCH_FILES = ("sequences.csv", "sequences.review.json", "sequences.backlog.csv",
               "sequences.downloaded.json")


def _emails(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        key = next((k for k in (rd.fieldnames or []) if k and k.strip().lower() == "email"), None)
        return {(r.get(key) or "").strip().lower() for r in rd if key and r.get(key)}


def downloaded_emails(home: Path, downloads: Path, since: float) -> set[str]:
    """Addresses the previous batch's downloads carried: the gate's own record,
    plus any CSV in ~/Downloads written after the batch that has an email
    column (the gate names them all-emails.csv / <pack>-emails.csv)."""
    out: set[str] = set()
    rec = home / "sequences.downloaded.json"
    if rec.exists():
        try:
            out |= {e.strip().lower() for e in json.loads(rec.read_text()).get("emails") or []}
        except (OSError, ValueError):
            pass
    if downloads.is_dir():
        for f in downloads.glob("*.csv"):
            try:
                if f.stat().st_mtime >= since:
                    out |= _emails(f)
            except OSError:
                continue
    return out


def return_undownloaded(home: Path, ledger: Path, downloads: Path) -> tuple[int, int]:
    """(returned, kept): take the previous batch's never-downloaded prospects
    off the ledger. Returns (0, 0) when there is no previous batch."""
    batch_csv = home / "sequences.csv"
    batch = _emails(batch_csv)
    if not batch or not ledger.exists():
        return 0, 0
    sent = downloaded_emails(home, downloads, batch_csv.stat().st_mtime)
    back = batch - sent
    if back:
        with ledger.open(newline="", encoding="utf-8") as fh:
            rd = csv.DictReader(fh)
            fields = rd.fieldnames or ["email", "first_seen"]
            rows = [r for r in rd if (r.get("email") or "").strip().lower() not in back]
        tmp = ledger.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        tmp.replace(ledger)
    return len(back), len(batch) - len(back)


def archive_batch(home: Path) -> str | None:
    """Move the previous batch's files to sequences-<its date>.*; the date is
    the review's `generated_at` (else the CSV's mtime). A name already taken
    gets -2, -3..."""
    csv_path = home / "sequences.csv"
    if not csv_path.exists():
        return None
    stamp = datetime.fromtimestamp(csv_path.stat().st_mtime).strftime("%Y-%m-%d")
    try:
        gen = json.loads((home / "sequences.review.json").read_text()).get("generated_at") or ""
        stamp = gen[:10] or stamp
    except (OSError, ValueError):
        pass
    tag, n = stamp, 2
    while (home / f"sequences-{tag}.csv").exists():
        tag, n = f"{stamp}-{n}", n + 1
    for name in BATCH_FILES:
        src = home / name
        if src.exists():
            dst = home / name.replace("sequences", f"sequences-{tag}", 1)
            shutil.move(str(src), str(dst))
    return tag


def status_path(home: Path) -> Path:
    return home / "logs" / "nightly-status.json"


def read_status(home: Path) -> dict[str, Any]:
    try:
        return json.loads(status_path(home).read_text())
    except (OSError, ValueError):
        return {}


def write_status(home: Path, state: str, **fields: Any) -> None:
    """building | ready | failed, plus the night it is for (the start date),
    the times and, for a failure, the reason and the next retry."""
    path = status_path(home)
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": state, **fields}, indent=1))
    tmp.replace(path)


def next_try(now: datetime) -> str | None:
    """The next launchd start tonight ("4:00 am"), or None after the last."""
    later = [h for h in RUN_HOURS if h > now.hour]
    return f"{later[0]}:00 am" if later else None


def built_tonight(home: Path, now: datetime | None = None) -> bool:
    """Tonight's batch is already built: a retry has nothing to do."""
    st = read_status(home)
    return st.get("state") == "ready" and st.get("night") == (now or datetime.now()).date().isoformat()


def refresh_running() -> bool:
    return (morning.INVENTORY_REPO / "logs" / ".refresh.lock").exists()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--home", type=Path, default=morning.ROOT,
                    help="where the batch, ledger and prospect list live (the main checkout)")
    ap.add_argument("--target", type=int, default=TARGET)
    ap.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    ap.add_argument("--dry-run", action="store_true", help="report steps 1-4, generate nothing")
    ap.add_argument("--built-tonight", action="store_true",
                    help="exit 0 if tonight's batch is already built, else 1; do nothing else")
    a = ap.parse_args(argv)
    home = a.home.resolve()
    if a.built_tonight:
        return 0 if built_tonight(home) else 1
    if a.dry_run:
        return _run(a, home)
    started = datetime.now()
    write_status(home, "building", night=started.date().isoformat(),
                 started=started.isoformat(timespec="seconds"))
    try:
        return _run(a, home, started)
    except Exception as exc:  # noqa: BLE001 -- recorded for the page, then raised
        _failed(home, started, f"the run crashed ({type(exc).__name__}: {str(exc)[:120]})")
        raise


def _failed(home: Path, started: datetime, reason: str) -> None:
    now = datetime.now()
    write_status(home, "failed", night=started.date().isoformat(),
                 started=started.isoformat(timespec="seconds"),
                 finished=now.isoformat(timespec="seconds"), reason=reason, next_try=next_try(now))


def _run(a: argparse.Namespace, home: Path, started: datetime | None = None) -> int:
    data = home / "system_b" / "data"
    ledger, prospects = data / "seen-prospects.csv", data / "prospects.csv"
    lines: list[str] = [f"nightly batch {datetime.now():%Y-%m-%d %H:%M}"]

    def say(msg: str) -> None:
        print(msg, flush=True)
        lines.append(msg)

    def finish(code: int, reason: str = "", **ready: Any) -> int:
        logs = home / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "nightly-latest.txt").write_text("\n".join(lines) + "\n")
        if started is not None:
            if code == 0:
                write_status(home, "ready", night=started.date().isoformat(),
                             started=started.isoformat(timespec="seconds"),
                             finished=datetime.now().isoformat(timespec="seconds"), **ready)
            else:
                _failed(home, started, reason)
        return code

    if a.dry_run:
        batch = _emails(home / "sequences.csv")
        sent = downloaded_emails(home, a.downloads, (home / "sequences.csv").stat().st_mtime) \
            if batch else set()
        say(f"1 · would return {len(batch - sent)} of {len(batch)} (downloaded: {len(batch & sent)})")
    else:
        back, kept = return_undownloaded(home, ledger, a.downloads)
        if back or kept:
            say(f"1 · previous batch: {kept} downloaded, {back} never downloaded and put back on the queue")
        tag = archive_batch(home)
        say(f"2 · archived the previous batch as sequences-{tag}.*" if tag else "2 · no previous batch")

    if refresh_running():
        say("3 · inventory refresh is running: using the files already published")
    elif not a.dry_run:
        statuses = morning.pull()
        bad = [f"{k}: {s}" for k, s in statuses.items() if not s.startswith("published")]
        say("3 · inventory published" + (f" ({len(bad)} file(s) kept as they were)" if bad else ""))

    problems, warnings = morning.check()
    unsent, total = morning.prospect_runway(prospects, ledger)
    say(f"4 · prospects: {unsent:,} unsent of {total:,} (~{unsent // max(a.target, 1)} nights)")
    if unsent < LOW_RUNWAY:
        say(f"    pull a new Apollo list: under {LOW_RUNWAY} prospects left")
    for p in problems:
        say(f"    STOP {p}")
    if problems or unsent == 0:
        say("not generating tonight.")
        return finish(1, problems[0] if problems else "no prospects left: pull a new Apollo list")
    if a.dry_run:
        return finish(0)

    out = home / "sequences.csv"
    cmd = [sys.executable, "-m", "system_b.run", "--pack", "cfo", "--in", str(prospects),
           "--out", str(out), "--target", str(a.target), "--ledger", str(ledger),
           "--allocations", str(data / "lead-allocations.csv")]
    env = {**os.environ, "LEADGEN_INVENTORY_DIR": str(morning.INVENTORY_DIR),
           "LEADGEN_BLOB_BASE_URL": ""}
    say(f"5 · generating up to {a.target}")
    proc = subprocess.run(cmd, env=env, check=False)
    review_path = home / "sequences.review.json"
    if proc.returncode != 0 or not review_path.exists():
        say(f"    generation failed (exit {proc.returncode}); see logs/nightly.log")
        return finish(1, f"building the emails failed (exit {proc.returncode}); see logs/nightly.log")

    review = json.loads(review_path.read_text())
    result = checks.check_batch(review, checks.read_rows(out))
    review["checks"] = result
    review_path.write_text(json.dumps(review, indent=1, default=str))
    s = result["summary"]
    say(f"6 · {s['prospects']} emails ready: {s['industry_match']} industry match, "
        f"{s['location_only']} location only, {s['no_gift']} skipped · "
        f"{s['fix']} to fix, {s['look']} to look at")
    for i in result["items"]:
        if i["kind"] == "fix":
            say(f"    fix  {i['company']}: {i['what']}")
    say("review: http://127.0.0.1:8000")
    return finish(0, emails=s["prospects"], fix=s["fix"], look=s["look"])


if __name__ == "__main__":
    sys.exit(main())
