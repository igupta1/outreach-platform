"""Cache and checkpoint for the corpus crawl.

Two stores, on purpose:

  * SQLite  -- one row per FIRM (keyed by domain), holding crawl outcome and,
    later, extraction. Checkpointed per firm so a stopped run resumes.
  * disk    -- the raw rendered HTML, one file per page. Extraction logic will
    change more than once; re-running it against cached HTML costs seconds,
    whereas re-crawling costs an hour of browser time.

Keyed by DOMAIN rather than by email or company name. The three lists overlap
by roughly 900 emails and Apollo's company names disagree with the sites' own
("GODIRECTINC.COM" vs "Go Direct"), but a domain is a domain.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent / "data" / "corpus"
DB = ROOT / "corpus.db"
HTML = ROOT / "html"

_DDL = """
CREATE TABLE IF NOT EXISTS firms (
    domain          TEXT PRIMARY KEY,
    website         TEXT NOT NULL,
    company         TEXT,
    source_lists    TEXT,          -- which of the three Apollo lists it came from
    emails          TEXT,          -- every deduped contact at this firm
    -- pass 1: crawl
    pages_tried     INTEGER,
    pages_ok        INTEGER,
    chars_regex     INTEGER,       -- what the no-JS fetcher returns
    chars_rendered  INTEGER,       -- what a headless browser returns
    fetch_error     TEXT,          -- set only when NOTHING could be fetched
    crawled_at      TIMESTAMP,
    -- pass 2: extraction
    extraction      TEXT,          -- verified JSON, see extract.py
    extracted_at    TIMESTAMP
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ")


def domain_of(url: str | None) -> str:
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    return re.sub(r"^www\.", "", u).split("/")[0]


def connect() -> sqlite3.Connection:
    ROOT.mkdir(parents=True, exist_ok=True)
    HTML.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(_DDL)
    return conn


def seed(conn: sqlite3.Connection, firms: list[dict[str, Any]]) -> int:
    added = 0
    with conn:
        for f in firms:
            cur = conn.execute(
                """INSERT INTO firms (domain, website, company, source_lists, emails)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(domain) DO UPDATE SET
                     source_lists=excluded.source_lists, emails=excluded.emails""",
                (f["domain"], f["website"], f.get("company"),
                 ",".join(sorted(f["source_lists"])), ",".join(sorted(f["emails"]))))
            added += 1 if cur.rowcount == 1 else 0
    return added


def pending(conn: sqlite3.Connection, stage: str) -> list[sqlite3.Row]:
    col = {"crawl": "crawled_at", "extract": "extracted_at"}[stage]
    sql = f"SELECT * FROM firms WHERE {col} IS NULL"
    if stage == "extract":
        sql += " AND crawled_at IS NOT NULL AND pages_ok > 0"
    return list(conn.execute(sql))


def save_crawl(conn: sqlite3.Connection, domain: str, **kw: Any) -> None:
    with conn:
        conn.execute(
            """UPDATE firms SET pages_tried=?, pages_ok=?, chars_regex=?,
                                chars_rendered=?, fetch_error=?, crawled_at=?
               WHERE domain=?""",
            (kw.get("pages_tried", 0), kw.get("pages_ok", 0), kw.get("chars_regex", 0),
             kw.get("chars_rendered", 0), kw.get("fetch_error") or "", _now(), domain))


def save_extraction(conn: sqlite3.Connection, domain: str, payload: dict) -> None:
    with conn:
        conn.execute("UPDATE firms SET extraction=?, extracted_at=? WHERE domain=?",
                     (json.dumps(payload), _now(), domain))


def _page_path(domain: str, url: str) -> Path:
    d = HTML / domain[:2] / domain
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html.gz")


def write_page(domain: str, url: str, html: str) -> None:
    p = _page_path(domain, url)
    with gzip.open(p, "wt", encoding="utf-8", errors="ignore") as fh:
        fh.write(f"<!--SOURCE_URL:{url}-->\n{html}")


def read_pages(domain: str) -> dict[str, str]:
    """`{url: html}` for a firm, from the disk cache. Extraction reads this, so
    changing the extraction prompt never means crawling again."""
    d = HTML / domain[:2] / domain
    out: dict[str, str] = {}
    if not d.exists():
        return out
    for p in d.glob("*.html.gz"):
        try:
            with gzip.open(p, "rt", encoding="utf-8", errors="ignore") as fh:
                blob = fh.read()
        except OSError:
            continue
        m = re.match(r"<!--SOURCE_URL:(.*?)-->\n", blob)
        if m:
            out[m.group(1)] = blob[m.end():]
    return out
