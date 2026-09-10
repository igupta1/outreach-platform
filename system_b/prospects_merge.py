"""Merge the Apollo exports into ONE deduplicated prospect list.

    python -m system_b.prospects_merge FractionalCFO.csv Accounting.csv Bookkeeping.csv

Three exports, one per service rung, and they overlap: 2,438 rows collapse to
1,559 firms. The overlap is the point rather than a mistake -- most small
finance practices sell all three, which is why the rung a firm belongs to is
read off their WEBSITE at generation time (`research/rung.py`) instead of
inferred from which file they arrived in.

One contact per firm. A second person at the same practice is the same
conversation, and emailing both reads as a mail-merge rather than as someone
who looked them up.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

# APOLLO's own header names, deliberately. `prospects.read_apollo_csv` is the
# one loader in the pipeline and it speaks Apollo; emitting tidier names here
# would mean teaching it a second dialect for no gain. The merged file is a
# smaller Apollo export, not a new format.
COLUMNS = ["Company Name", "First Name", "Last Name", "Title", "Email",
           "Website", "Person Linkedin Url", "Company City", "Company State",
           "_source", "_corpus_serves"]

# Whose email to keep when a firm has several. A founder answers for the
# practice; a staff accountant forwards it, or does not.
_TITLE_RANK = (
    (re.compile(r"founder|owner|principal|managing (partner|director)", re.IGNORECASE), 0),
    (re.compile(r"\bceo\b|chief executive|president", re.IGNORECASE), 1),
    (re.compile(r"partner|director", re.IGNORECASE), 2),
)


def _rank(title: str | None) -> int:
    for pattern, score in _TITLE_RANK:
        if pattern.search(title or ""):
            return score
    return 9


def domain_of(url: str | None) -> str:
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0].strip()


def merge(paths: list[Path]) -> tuple[list[dict], Counter]:
    best: dict[str, dict] = {}
    stats: Counter = Counter()
    for path in paths:
        source = path.stem
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                stats["rows"] += 1
                domain = domain_of(row.get("Website"))
                email = (row.get("Email") or "").strip()
                if not domain or not email:
                    stats["dropped_no_domain_or_email"] += 1
                    continue
                title = row.get("Title") or ""
                candidate = {
                    "Company Name": (row.get("Company Name") or domain).strip(),
                    "First Name": (row.get("First Name") or "").strip(),
                    "Last Name": (row.get("Last Name") or "").strip(),
                    "Title": title.strip(),
                    "Email": email,
                    "Website": (row.get("Website") or "").strip(),
                    "Person Linkedin Url": (row.get("Person Linkedin Url")
                                            or row.get("Company Linkedin Url") or "").strip(),
                    "Company City": (row.get("Company City") or row.get("City") or "").strip(),
                    "Company State": (row.get("Company State") or row.get("State") or "").strip(),
                    "_source": source,
                }
                held = best.get(domain)
                if held is None:
                    best[domain] = candidate
                elif _rank(title) < _rank(held["Title"]):
                    # Better-titled contact at a firm we already have. Keep the
                    # sources joined so the review card can show that this firm
                    # appeared in more than one export.
                    candidate["_source"] = f"{held['_source']}+{source}" \
                        if source not in held["_source"] else held["_source"]
                    best[domain] = candidate
                elif source not in held["_source"]:
                    held["_source"] = f"{held['_source']}+{source}"
    stats["firms"] = len(best)
    return list(best.values()), stats


# --- Ordering ---------------------------------------------------------------
#
# The corpus already holds a crawl of these same firms, including the verbatim
# industries each one says it serves. It is not accurate enough to CLAIM a
# vertical from -- generation re-crawls every prospect and re-verifies the
# phrase, because a stale crawl must never put words in a firm's mouth -- but
# it is a perfectly good way to decide who to look at FIRST.
#
# That matters because every prospect costs a live website crawl. In
# alphabetical order the run grinds through hundreds of firms that serve
# construction or dentists before reaching one that serves nonprofits. Sorting
# by what the corpus last saw puts the likely matches at the front, so a
# 20-prospect batch costs roughly 20 crawls instead of several hundred.

CORPUS_DB = Path(__file__).resolve().parent / "data" / "corpus" / "corpus.db"

_SERVED = {
    "nonprofit": re.compile(r"non[- ]?profit|501\(?c\)?", re.IGNORECASE),
    "funds": re.compile(r"private equity|venture capital|\bvc\b|\bfund manager"
                        r"|hedge fund|investment adviser|\bfunds?\b", re.IGNORECASE),
    "ecommerce": re.compile(r"e-?commerce|shopify|dtc|direct[- ]to[- ]consumer", re.IGNORECASE),
}


def corpus_hints() -> dict[str, str]:
    """{domain: "nonprofit,funds"} from the last crawl. Empty when unavailable."""
    import json
    import sqlite3

    if not CORPUS_DB.exists():
        return {}
    out: dict[str, str] = {}
    try:
        conn = sqlite3.connect(f"file:{CORPUS_DB}?mode=ro", uri=True)
        rows = conn.execute("SELECT domain, extraction FROM firms "
                            "WHERE extraction IS NOT NULL")
    except sqlite3.Error:
        return {}
    for domain, raw in rows:
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        text = " | ".join(
            str(s.get("phrase", "")) for s in (data.get("specialties") or [])
            if isinstance(s, dict))
        hit = [k for k, pattern in _SERVED.items() if pattern.search(text)]
        if hit:
            out[(domain or "").lower()] = ",".join(hit)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prospects_merge", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent / "data" / "prospects.csv")
    a = ap.parse_args(argv)

    rows, stats = merge(a.inputs)
    # Likely matches first (see `corpus_hints`), then alphabetical inside each
    # group so the order is stable between runs.
    hints = corpus_hints()
    live = {"nonprofit", "funds"}          # ecommerce is deferred on Apollo cost
    for row in rows:
        row["_corpus_serves"] = hints.get(domain_of(row["Website"]), "")
    rows.sort(key=lambda r: (
        0 if set((r["_corpus_serves"] or "").split(",")) & live else
        1 if r["_corpus_serves"] else 2,
        r["Company Name"].lower(),
    ))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"[merge] {stats['rows']:,} rows -> {stats['firms']:,} firms -> {a.out}")
    if stats["dropped_no_domain_or_email"]:
        print(f"[merge] dropped {stats['dropped_no_domain_or_email']:,} "
              "row(s) with no website or no email")
    mix = Counter(r["_source"] for r in rows)
    for src, n in mix.most_common(8):
        print(f"           {src:34} {n:>5}")
    served = Counter(r["_corpus_serves"] for r in rows if r["_corpus_serves"])
    if served:
        ready = sum(n for k, n in served.items()
                    if {"nonprofit", "funds"} & set(k.split(",")))
        print(f"[merge] {ready:,} firm(s) last seen serving nonprofits or funds "
              "— sorted to the front")
    return 0


if __name__ == "__main__":
    sys.exit(main())
