"""The day's LinkedIn connection list, merged across every pack.

    system_b/.venv/bin/python -m system_b.connect_queue \
        cfo.review.json acct.review.json book.review.json --top 20

Each pack is generated and reviewed on its own, so each writes its own review
JSON. But the LinkedIn cap is not per-pack — it is one budget of ~20-25 requests
a day across everything you are running. Working three files down separately
spends that budget on whoever happens to sit at the top of each, which is three
separate answers to a question that has one.

So this merges them and answers it once: the N most-personalized prospects you
have, in order, regardless of which pack they came from.

Ordering is `personalization.rank` — the same rank the review gate sorts by and
the same one the exported CSV rows are in. It is derived from the gates the copy
actually used (a claimed vertical, named clients, a stated revenue range,
geography), not from what we happen to know about a prospect, so the top of this
list is genuinely the mail that reads least like a template.

Prospects with no `linkedin` URL are dropped: there is nothing to connect to.
They still get their email — this file is only the second channel.

Send-free and read-only, like the review gate: it reads JSON and writes a CSV.
Nothing here talks to LinkedIn, and nothing can — automating connection requests
is against LinkedIn's ToS and the account is attached to a day job.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

# What the operator needs to work the list: who, where they came from, the link
# to click, and why they are this high (so a thin-looking row is explicable
# rather than suspicious). The DM text is deliberately NOT here — it lives in
# the history sheet, which is where you look weeks later when they accept.
COLUMNS = [
    "rank", "pack", "personalization", "first_name", "last_name",
    "company", "city", "state", "linkedin_url", "email",
]


def _rank(prospect: dict[str, Any]) -> int:
    """The prospect's personalization rank; unranked sorts last."""
    return ((prospect.get("personalization") or {}).get("rank") or 99)


def _label(prospect: dict[str, Any]) -> str:
    return (prospect.get("personalization") or {}).get("label") or ""


def load_reviews(paths: list[Path]) -> list[dict[str, Any]]:
    """Every prospect across every review file, tagged with its pack. A missing
    or unreadable file is reported and skipped — one bad path must not cost you
    the rest of the day's list."""
    out: list[dict[str, Any]] = []
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[skip] {path}: {exc}")
            continue
        pack = doc.get("pack") or path.stem
        for prospect in doc.get("prospects") or []:
            out.append({**prospect, "_pack": pack})
    return out


def build_queue(prospects: list[dict[str, Any]], *, top: int) -> list[dict[str, Any]]:
    """The top `top` connectable prospects, most-personalized first.

    Company name breaks ties so the order is stable run to run, matching how
    `run.py` sorts its own rows. Anyone without a LinkedIn URL is dropped before
    the cut, so a full list of 20 is 20 people you can actually act on rather
    than 20 rows of which some are dead."""
    connectable = [p for p in prospects if (p.get("linkedin") or "").strip()]
    connectable.sort(key=lambda p: (_rank(p), (p.get("company") or "").lower()))
    rows: list[dict[str, Any]] = []
    for i, p in enumerate(connectable[:top], start=1):
        rows.append({
            "rank": i,
            "pack": p["_pack"],
            "personalization": _label(p),
            "first_name": p.get("first_name") or "",
            "last_name": p.get("last_name") or "",
            "company": p.get("company") or "",
            "city": p.get("city") or "",
            "state": p.get("state") or "",
            "linkedin_url": (p.get("linkedin") or "").strip(),
            "email": p.get("email") or "",
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Merge every pack's review JSON into one LinkedIn connection list."
    )
    ap.add_argument("reviews", nargs="+", type=Path,
                    help="review JSON files (one per pack run)")
    ap.add_argument("--top", type=int, default=20,
                    help="how many to queue — set it to your daily connection cap "
                         "(default: 20)")
    ap.add_argument("--out", type=Path, default=Path("connect-queue.csv"),
                    help="output CSV (default: connect-queue.csv)")
    args = ap.parse_args(argv)

    prospects = load_reviews(args.reviews)
    if not prospects:
        print("[connect] no prospects found in those review files")
        return 1

    rows = build_queue(prospects, top=args.top)
    no_linkedin = len(prospects) - len([p for p in prospects if (p.get("linkedin") or "").strip()])

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    by_pack: dict[str, int] = {}
    for r in rows:
        by_pack[r["pack"]] = by_pack.get(r["pack"], 0) + 1
    print(f"[connect] {len(prospects)} prospect(s) across {len(args.reviews)} pack file(s)"
          f"{f', {no_linkedin} with no linkedin url' if no_linkedin else ''}")
    print(f"[connect] wrote {len(rows)} to {args.out}  ·  {by_pack}")
    for r in rows:
        print(f"  {r['rank']:>3}. [{r['pack']:<11}] {r['first_name']} {r['last_name']} "
              f"· {r['company']}  ({r['personalization']})")
        print(f"       {r['linkedin_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
