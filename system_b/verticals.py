"""Sort a prospect list into one CSV per served vertical.

    system_b/.venv/bin/python -m system_b.verticals \
        --in FractionalCFO.csv Accounting.csv Bookkeeping.csv --out verticals/

Reads each Apollo export, runs the SAME Gate A research the pipeline uses --
fetch the firm's site, let an LLM propose the customer industries it states,
then verify each phrase appears word-for-word on a fetched page -- and writes
one CSV per vertical, carrying every original column through untouched.

## Why sort at all

A niched email is the strongest thing this system sends: it opens on a vertical
the prospect stated on their own site, and the gift is companies in that same
vertical. Which prospects can get one is decided by Gate A, and today that is
discovered DURING a run, one prospect at a time, after the money is spent.
Knowing it up front turns it into a targeting decision: work the healthcare
bookkeepers as one batch, and their gifts all come from one pool.

## What this is not

It is not a substitute for the research the pipeline does at generation time.
That has to be fresh -- a site changes, and copy must never claim something
verified months ago. This is a SORTING pass over the prospect list; `run.py`
still researches every prospect it sequences.

## Cost

Measured over 2,436 prospects: ~2.9 pages fetched each, ~4,300 input tokens per
classification, roughly $2-3 total on gpt-4o-mini and 15-30 minutes wall clock.
Results are cached by domain, so a re-run only pays for prospects it has not
seen -- adding a fourth list costs only that list.

The source CSVs are opened read-only and never rewritten.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from system_b import config
from system_b.clients.inventory import load_taxonomy
from system_b.copy.lex import niche_display
from system_b.research.service import research_prospect

CACHE = Path(__file__).resolve().parent / "data" / "verticals.db"
_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG.sub("-", (s or "").lower()).strip("-") or "unknown"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS classified (
            website        TEXT PRIMARY KEY,
            firm           TEXT,
            classification TEXT,     -- niched | generalist
            vertical       TEXT,     -- the clean label copy would use
            match_param    TEXT,     -- kind=token, what the gift matches on
            all_verticals  TEXT,     -- every mappable industry they state
            phrase         TEXT,     -- their exact words
            evidence_url   TEXT,
            flags          TEXT,
            checked_at     TIMESTAMP)""")
    return conn


def _cached(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["website"]: r for r in conn.execute("SELECT * FROM classified")}


def classify_one(row: dict[str, Any], taxonomy: dict) -> dict[str, Any]:
    """Gate A for one prospect. Never raises -- an unreachable site is a
    generalist, which is exactly how the pipeline treats it."""
    out = {"website": row["website"], "firm": row.get("firm_name") or "",
           "classification": "generalist", "vertical": "", "match_param": "",
           "all_verticals": "", "phrase": "", "evidence_url": "", "flags": ""}
    try:
        res = research_prospect(row["website"], taxonomy)
    except Exception as exc:                       # noqa: BLE001
        out["flags"] = f"error: {type(exc).__name__}"
        return out
    out["classification"] = res.classification
    out["phrase"] = res.niche_phrase or ""
    out["flags"] = " | ".join(res.flags or [])
    if res.evidence:
        out["evidence_url"] = res.evidence[0].url
    labels = []
    for mp in (res.candidate_match_params or []):
        lab = niche_display(mp)
        if lab and lab not in labels:
            labels.append(lab)
    out["all_verticals"] = ", ".join(labels)
    if res.match_param:
        # The label COPY would use. A token with no curated label renders as
        # generalist (see `niche_display`), so it is not a vertical we can sort
        # on either -- filing it under the raw token would invent a bucket the
        # emails can never mention.
        out["vertical"] = niche_display(res.match_param) or ""
        out["match_param"] = f"{res.match_param[0]}={res.match_param[1]}"
    return out


def run(sources: list[Path], out_dir: Path, *, workers: int, cache: Path,
        limit: int | None = None) -> int:
    taxonomy = load_taxonomy()
    if not taxonomy:
        print("[warn] no taxonomy available — every prospect will read as generalist")
    conn = _connect(cache)
    have = _cached(conn)

    per_source: dict[Path, list[dict]] = {}
    todo: list[dict] = []
    for src in sources:
        from system_b.prospects import read_apollo_csv
        rows = read_apollo_csv(src)[: limit or None]
        per_source[src] = rows
        for r in rows:
            if r["website"] not in have:
                todo.append(r)
    # dedupe: the three lists overlap heavily, and a site is a site
    seen: set[str] = set()
    todo = [r for r in todo if not (r["website"] in seen or seen.add(r["website"]))]
    print(f"[verticals] {sum(len(v) for v in per_source.values())} prospect(s) across "
          f"{len(sources)} list(s); {len(have)} cached, {len(todo)} to classify")

    if todo:
        config.require("OPENAI_API_KEY")
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for res in pool.map(lambda r: classify_one(r, taxonomy), todo):
                with conn:
                    conn.execute(
                        """INSERT OR REPLACE INTO classified
                           (website, firm, classification, vertical, match_param,
                            all_verticals, phrase, evidence_url, flags, checked_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (*[res[k] for k in ("website", "firm", "classification", "vertical",
                                            "match_param", "all_verticals", "phrase",
                                            "evidence_url", "flags")],
                         datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=' ')))
                done += 1
                if done % 100 == 0:
                    print(f"[verticals] {done}/{len(todo)} classified", flush=True)
        have = _cached(conn)

    # --- write one CSV per vertical, per source list -------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Counter] = {}
    for src, rows in per_source.items():
        stem = src.stem
        buckets: dict[str, list[dict]] = defaultdict(list)
        with open(src, newline="", encoding="utf-8-sig") as fh:
            raw = {(_norm(r.get("Website")) or ""): r for r in csv.DictReader(fh)}
            fieldnames = list(next(iter(raw.values())).keys()) if raw else []
        for r in rows:
            c = have.get(r["website"])
            vertical = (c["vertical"] if c else "") or "_generalist"
            original = raw.get(r["website"]) or {}
            enriched = dict(original)
            enriched["_vertical"] = vertical if vertical != "_generalist" else ""
            enriched["_all_verticals"] = c["all_verticals"] if c else ""
            enriched["_stated_phrase"] = c["phrase"] if c else ""
            enriched["_evidence_url"] = c["evidence_url"] if c else ""
            buckets[vertical].append(enriched)
        d = out_dir / stem
        d.mkdir(parents=True, exist_ok=True)
        cols = fieldnames + ["_vertical", "_all_verticals", "_stated_phrase", "_evidence_url"]
        for vertical, items in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            path = d / f"{_slug(vertical)}.csv"
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(items)
        summary[stem] = Counter({k: len(v) for k, v in buckets.items()})
        print(f"\n[{stem}] {len(rows)} prospects -> {len(buckets)} file(s) in {d}")
        for k, n in summary[stem].most_common(12):
            print(f"    {n:4}  {k}")
    return 0


def _norm(u: str | None) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="sources", nargs="+", required=True, type=Path)
    ap.add_argument("--out", dest="out_dir", type=Path, default=Path("verticals"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--limit", type=int, default=0, help="first N per list (for a dry run)")
    a = ap.parse_args(argv)
    return run(a.sources, a.out_dir, workers=a.workers, cache=a.cache, limit=a.limit or None)


if __name__ == "__main__":
    sys.exit(main())
