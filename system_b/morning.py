"""One command for the daily batch: pull, check, generate, review.

    python -m system_b.morning

The three lead magnets refresh themselves on GitHub Actions. This is the other
half -- everything that happens on your machine, in the order it has to happen,
so the morning is one command rather than four and a checklist.

    1. PULL      the newest inventory artifact from each magnet repo
    2. CHECK     refuse to run, and say why, if something is wrong
    3. GENERATE  build the batch
    4. REVIEW    open the review gate in a browser

## Why artifacts and not a blob store

The magnets publish their inventory as a GitHub Actions artifact and this
downloads it with `gh`. The alternative -- a Vercel Blob, which the retired
job-post pipeline used -- would mean standing up a project and holding a write
token purely to move 13 MB between two machines that already authenticate to
GitHub. `gh run download` needs no new service and no new secret.

## Why the check comes before the work

Every failure this guards against is one you would otherwise discover after
spending the morning on it: an inventory that stopped refreshing two months
ago, a prospect queue with nine names left, a batch that came out empty because
every remaining prospect was already emailed. Each is cheap to detect and
expensive to find late.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import subprocess
import sys
import webbrowser
from datetime import date, datetime, timezone
from pathlib import Path

from system_b.clients.inventory import MAGNET_MAX_AGE_DAYS, MAGNETS

ROOT = Path(__file__).resolve().parent.parent
INVENTORY_DIR = ROOT / "system_b" / "data" / "inventory"

# magnet key -> (GitHub repo, artifact name)
SOURCES: dict[str, tuple[str, str]] = {
    "nonprofit": ("igupta1/Nonprofit", "nonprofit-leads"),
    "funds": ("igupta1/Funds", "fund-leads"),
    "ecommerce": ("igupta1/Ecommerce", "ecommerce-leads"),
}

# Below this many unsent prospects, say so. Not an error -- you can still send
# today -- but the list is the thing that runs out first, and finding that out
# with a week of runway left is very different from finding out on the day.
LOW_PROSPECTS = 60


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)


# --- 1. pull ---------------------------------------------------------------


def _lead_count(path: Path) -> int:
    """Leads in an inventory file; 0 for missing, empty or unreadable."""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0
    return data.get("count") or len(data.get("leads") or [])


def pull(only: str | None = None) -> dict[str, str]:
    """Download the newest inventory artifact per magnet. Returns {key: status}.

    A magnet that fails to download is NOT fatal: the three refresh on their
    own cadences, the local copy from last time is still on disk, and a run
    with yesterday's funds data is a useful run. The freshness check that
    follows is what decides whether it is too old to use."""
    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not shutil.which("gh"):
        return {k: "no gh CLI — using the local copy" for k in SOURCES}

    out: dict[str, str] = {}
    for key, (repo, artifact) in SOURCES.items():
        if only and key != only:
            continue
        # Into a TEMP dir, then move into place. `gh run download` refuses to
        # overwrite a file that already exists -- "error extracting zip
        # archive: ... file exists" -- so downloading straight into
        # INVENTORY_DIR worked exactly ONCE and failed silently every run
        # after, reporting "kept local copy" as if the artifact were simply
        # missing. Nothing downstream would have caught it: nonprofit's
        # freshness limit is 400 days.
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(["gh", "run", "download", "--repo", repo,
                         "--name", artifact, "--dir", tmp])
            got = list(Path(tmp).glob("*.json"))
            if proc.returncode == 0 and got:
                dest = INVENTORY_DIR / got[0].name
                fresh, have = _lead_count(got[0]), _lead_count(dest)
                # NEVER trade a populated inventory for an empty one. The very
                # first funds run published 231 bytes of zero leads before the
                # workflow had a health check, and pulling it overwrote a good
                # 359-lead file -- a download that destroys working data is
                # worse than no download. The magnet's own health check is the
                # real defence; this is the second one, on this side.
                if have and not fresh:
                    out[key] = f"kept local copy ({have:,} leads; artifact was empty)"
                    continue
                shutil.move(str(got[0]), dest)
                out[key] = f"downloaded ({fresh:,} leads)"
            else:
                first = (proc.stderr or "").strip().splitlines()
                out[key] = ("kept local copy "
                            f"({first[0][:60] if first else 'no artifact yet'})")
    return out


# --- 2. check --------------------------------------------------------------


def check(today: date | None = None) -> tuple[list[str], list[str]]:
    """(blocking problems, warnings). Blocking means do not generate."""
    # UTC, because `generated_at` is UTC. On the local date a magnet that
    # published at 01:30 UTC read as "-1d old" from Pacific time -- harmless to
    # the comparison, but a negative age in the one report that exists to tell
    # you whether the data is stale reads as a broken check.
    today = today or datetime.now(timezone.utc).date()
    problems: list[str] = []
    warnings: list[str] = []

    for key, filename in MAGNETS.items():
        path = INVENTORY_DIR / filename
        if not path.exists():
            warnings.append(f"{key}: no inventory file — that magnet is skipped")
            continue
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            problems.append(f"{key}: inventory file is not valid JSON")
            continue
        count = data.get("count") or len(data.get("leads") or [])
        if not count:
            problems.append(f"{key}: inventory has ZERO leads")
            continue
        gen = str(data.get("generated_at") or "")[:10]
        try:
            age = (today - date.fromisoformat(gen)).days
        except ValueError:
            warnings.append(f"{key}: {count:,} leads, no generated_at — age unknown")
            continue
        cap = MAGNET_MAX_AGE_DAYS.get(key, 3)
        line = f"{key}: {count:,} leads, {age}d old"
        if age > cap:
            problems.append(f"{line} — past the {cap}d limit; re-run its workflow")
        else:
            warnings.append(line)

    if not any(not w.startswith(tuple(f"{k}: no inventory" for k in MAGNETS))
               for w in warnings) and not warnings:
        problems.append("no inventory at all — run the magnet workflows first")
    return problems, warnings


def prospect_runway(prospects: Path, ledger: Path) -> tuple[int, int]:
    """(unsent, total) prospects. The list is what runs out first."""
    import csv

    if not prospects.exists():
        return 0, 0
    with prospects.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    total = len(rows)

    def email_of(row: dict) -> str:
        """The email column, whatever it is called.

        The prospect file carries Apollo's "Email"; the ledger writes "email".
        Reading one spelling silently made EVERY prospect look already-sent:
        their address came back as "", the ledger's blank rows also yield "",
        and the two matched. The runway read 0 unsent of 1,557 and the whole
        batch refused to build. Case is not load-bearing here, so it is not
        trusted."""
        for key, value in row.items():
            if key and key.strip().lower() == "email":
                return (value or "").strip().lower()
        return ""

    sent: set[str] = set()
    if ledger.exists():
        with ledger.open(newline="", encoding="utf-8-sig") as fh:
            sent = {e for e in (email_of(r) for r in csv.DictReader(fh)) if e}
    unsent = sum(1 for r in rows if email_of(r) not in sent)
    return unsent, total


# --- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="morning", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prospects", type=Path,
                    default=ROOT / "system_b" / "data" / "prospects.csv")
    # seen-prospects.csv, NOT outreach-history.csv. The two files have
    # different jobs and different shapes, and pointing this at the wrong one
    # broke dedup silently: `run._append_ledger` writes two columns
    # (email, first_seen), the history sheet has seventeen starting with
    # `pack`, so every appended address landed under `pack` and the `email`
    # column stayed blank. `_load_ledger` reads `email` -- so it saw nothing,
    # and the 20 prospects sequenced on 2026-09-30 were still queued to go out
    # a second time. Nothing raised; the run printed "skipping 30" when the
    # file held 50 rows.
    ap.add_argument("--ledger", type=Path,
                    default=ROOT / "system_b" / "data" / "seen-prospects.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "sequences.csv")
    ap.add_argument("--pack", default="cfo",
                    help="FALLBACK voice only; the rung is read off each firm's site")
    ap.add_argument("--limit", type=int, default=20,
                    help="how many prospects to draft this morning")
    ap.add_argument("--skip-pull", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)

    print("═" * 66)
    print("  MORNING BATCH")
    print("═" * 66)

    if not a.skip_pull:
        print("\n1 · pulling the newest inventory")
        for key, status in pull().items():
            print(f"    {key:11} {status}")

    print("\n2 · checking")
    problems, warnings = check()
    for w in warnings:
        print(f"    ok   {w}")
    unsent, total = prospect_runway(a.prospects, a.ledger)
    if total:
        days = unsent // max(a.limit, 1)
        flag = "warn" if unsent < LOW_PROSPECTS else "ok  "
        print(f"    {flag} prospects: {unsent:,} unsent of {total:,} "
              f"(~{days} more batches at {a.limit}/day)")
        if unsent == 0:
            problems.append("every prospect has been emailed — add more to "
                            f"{a.prospects}")
    else:
        problems.append(f"no prospect list at {a.prospects}")

    for p in problems:
        print(f"    STOP {p}")
    if problems:
        print("\n  Not generating. Fix the above and re-run.")
        return 1
    if a.check_only:
        print("\n  Checks passed (--check-only, nothing generated).")
        return 0

    print(f"\n3 · generating up to {a.limit} sequence(s)")
    cmd = [sys.executable, "-m", "system_b.run", "--pack", a.pack,
           "--in", str(a.prospects), "--out", str(a.out),
           "--target", str(a.limit), "--ledger", str(a.ledger)]
    import os
    env = {**os.environ,
           "LEADGEN_INVENTORY_DIR": str(INVENTORY_DIR),
           # The magnets publish as GitHub artifacts now, not to a blob. A
           # LEADGEN_BLOB_BASE_URL left over in the shell would send every
           # inventory read to a dead Vercel store first and cost three failed
           # HTTP retries per magnet before falling back to the local file.
           "LEADGEN_BLOB_BASE_URL": ""}
    proc = subprocess.run(cmd, env=env, check=False)
    if proc.returncode != 0:
        print("\n  Generation failed — nothing to review.")
        return proc.returncode

    review = a.out.with_name(f"{a.out.stem}.review.json")
    print(f"\n4 · review gate  →  {review}")
    if not a.no_open:
        serve = subprocess.Popen(
            [sys.executable, "-m", "system_b.review.serve", str(review)])
        webbrowser.open("http://localhost:8000")
        print("    serving on http://localhost:8000 — ctrl-c when you are done")
        try:
            serve.wait()
        except KeyboardInterrupt:
            serve.terminate()
    print(f"\n  Done. {datetime.now():%H:%M}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
