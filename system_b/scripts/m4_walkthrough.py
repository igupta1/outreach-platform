"""M4 walkthrough — drive prospects end-to-end and review the output.

Per prospect:  research_and_write -> build_gift -> build_email_1 ->
assemble_review, writing the card + research + flags onto the Airtable row.
SENDS NOTHING; every row ends at review_status=pending.

Two output modes:
  (default)   full review card per prospect — good for a handful.
  --summary   one compact line per prospect + an aggregate tuning report —
              good for a whole CSV (still writes every card to Airtable).

Prospects come from the Airtable base (rows with a `website`) or an Apollo
CSV (--csv). Step-0 checks skip no-website, headcount > 10, duplicate domain.

Run (whole file, tuning report):
  system_b/.venv/bin/python -m system_b.scripts.m4_walkthrough \
      --csv system_b/apollo-contacts-export.csv --summary
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter
from datetime import date
from typing import Any
from urllib.parse import urlparse

from system_b import config
from system_b.clients.airtable_client import AirtableClient
from system_b.clients.scraper_client import ScraperClient, SnapshotScraper
from system_b.copy.email import build_email_1
from system_b.copy.llm import describe_leads
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.research.service import research_and_write
from system_b.review import assemble_review

SAMPLE_PROSPECTS: list[dict[str, str]] = [
    {"firm_name": "Example Fractional CFO", "website": "https://example.com",
     "city": "Denver", "state": "CO", "first_name": "there", "email": "", "linkedin": ""},
]


def _field(rec: dict[str, Any], key: str, default: str = "") -> str:
    return rec.get("fields", {}).get(key) or default


def load_prospects(at: AirtableClient, limit: int) -> list[dict[str, Any]]:
    rows = at.table.all(max_records=500)
    usable = [r for r in rows if _field(r, "website")]
    if usable:
        return [{
            "record_id": r["id"], "firm_name": _field(r, "firm_name"),
            "website": _field(r, "website"), "city": _field(r, "city") or None,
            "state": _field(r, "state") or None,
            "first_name": _field(r, "first_name") or _field(r, "contact_name") or None,
            "email": _field(r, "email"), "linkedin": _field(r, "linkedin"),
        } for r in usable[:limit]]

    print("[info] no rows with a website in the base — creating sample rows.")
    created = []
    for s in SAMPLE_PROSPECTS[:limit]:
        rec = at.create_prospect({
            "firm_name": s["firm_name"], "website": s["website"],
            "city": s["city"], "state": s["state"],
            "email": s.get("email", ""), "linkedin": s.get("linkedin", ""), "stage": "researched",
        })
        created.append({"record_id": rec["id"], **s})
    return created


def _domain(website: str) -> str:
    net = urlparse(website if "//" in website else f"//{website}").netloc.lower()
    return net[4:] if net.startswith("www.") else net


def parse_csv_rows(path: str, limit: int) -> list[dict[str, Any]]:
    """Map the first `limit` Apollo rows to prospect dicts. Pure — no network."""
    out: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for i, r in enumerate(csv.DictReader(f)):
            if i >= limit:
                break
            hc_raw = (r.get("# Employees") or "").strip()
            try:
                headcount = int(hc_raw) if hc_raw else None
            except ValueError:
                headcount = None
            out.append({
                "firm_name": (r.get("Company Name for Emails") or r.get("Company Name") or "").strip(),
                "website": (r.get("Website") or "").strip(),
                "city": (r.get("City") or r.get("Company City") or "").strip() or None,
                "state": (r.get("State") or r.get("Company State") or "").strip() or None,
                "first_name": (r.get("First Name") or "").strip() or None,
                "email": (r.get("Email") or "").strip(),
                "linkedin": (r.get("Person Linkedin Url") or "").strip(),
                "headcount": headcount,
            })
    return out


def _find_or_create(at: AirtableClient, p: dict[str, Any]) -> str:
    fields: dict[str, Any] = {"website": p["website"], "stage": "researched"}
    for k in ("city", "state", "email", "linkedin"):
        if p.get(k):
            fields[k] = p[k]
    existing = at.find_by_firm(p["firm_name"])
    if existing:
        at.update(existing["id"], fields)
        return existing["id"]
    fields["firm_name"] = p["firm_name"]
    return at.create_prospect(fields)["id"]


def load_from_csv(at: AirtableClient, path: str, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    prospects: list[dict[str, Any]] = []
    for p in parse_csv_rows(path, limit):
        if not p["website"]:
            print(f"[skip] {p['firm_name']!r}: no website"); continue
        if p["headcount"] is not None and p["headcount"] > 10:
            print(f"[skip] {p['firm_name']!r}: headcount {p['headcount']} > 10"); continue
        dom = _domain(p["website"])
        if dom and dom in seen:
            print(f"[skip] {p['firm_name']!r}: duplicate domain {dom}"); continue
        if dom:
            seen.add(dom)
        prospects.append({**p, "record_id": _find_or_create(at, p)})
    return prospects


def process_one(at: AirtableClient, sc: SnapshotScraper, taxonomy: dict, row: dict, today: date) -> dict[str, Any]:
    """Run one prospect end-to-end; write the card; return a result record.
    Raises on failure (caller records it as an error)."""
    rid = row["record_id"]
    research = research_and_write(rid, row["website"], taxonomy, at)
    prospect = Prospect(
        firm_name=row["firm_name"], city=row.get("city"), state=row.get("state"),
        classification=research.classification, match_param=research.match_param,
        niche_phrase=research.niche_phrase, niche_source=research.niche_source or "site",
        first_name=row.get("first_name"),
    )
    base = {
        "firm": row["firm_name"], "classification": research.classification,
        "niche_source": research.niche_source, "match_param": research.match_param,
        "niche_phrase": research.niche_phrase,
    }
    gift = build_gift(prospect, sc)
    if gift is None:
        return {**base, "status": "no_gift", "gift_size": 0, "flags": []}
    descriptions = describe_leads(gift, prospect)
    draft = build_email_1(gift, prospect, descriptions, today=today)
    contact = {"email": row.get("email", ""), "linkedin": row.get("linkedin", "")}
    fields = assemble_review(at, rid, prospect, gift, draft, research, contact=contact)
    return {
        **base, "status": "ok", "gift_size": gift.gift_size,
        "best_signal": gift.best_lead.signal_type, "geo": gift.geo_level,
        "shape": gift.subject_shape, "all_niche": gift.all_niche, "subject": draft.subject,
        "flags": [f for f in fields["flags"].split("\n") if f],
        "card": fields["review_card"], "queued": fields["queued_message"],
    }


def print_full(r: dict[str, Any]) -> None:
    print("\n" + "=" * 76)
    print(f"PROSPECT: {r['firm']}")
    print("=" * 76)
    if r["status"] == "error":
        print(f"  !! ERROR: {r['error']}"); return
    if r["status"] == "no_gift":
        print(f"  classification={r['classification']} — NO GIFT (0 leads matched)"); return
    print("\n" + r["card"])
    print("\n----- FLAGS -----")
    print("\n".join(r["flags"]) or "(none)")
    print("\n----- QUEUED MESSAGE (exact copy, NOT sent) -----")
    print(r["queued"])


def _niche(r: dict[str, Any]) -> str:
    mp = r.get("match_param")
    return f"{mp[0]}={mp[1]}" if mp else "-"


def print_compact(r: dict[str, Any]) -> None:
    firm = r["firm"][:30]
    if r["status"] == "error":
        print(f"  ✗ {firm:30} ERROR: {str(r['error'])[:60]}"); return
    if r["status"] == "no_gift":
        print(f"  – {firm:30} {r['classification']:10} NO GIFT"); return
    print(f"  ✓ {firm:30} {r['classification']:10} {_niche(r):22} "
          f"gift={r['gift_size']} best={r['best_signal']:13} geo={r['geo']:5} "
          f"{r['shape']:8} flags={len(r['flags'])}")


_FLAG_BUCKETS = [
    ("thin website", "thin-website"),
    ("not found verbatim", "hallucination-rejected"),
    ("no taxonomy match", "unmapped-niche"),
    ("presence-only", "client-list-presence-only"),
    ("LLM-classified", "llm-niche-check"),
    ("cfo_wanted", "cfo_wanted-livecheck"),
    ("null-niche", "null-niche"),
    ("domainless", "domainless"),
    ("registered address", "funding-city-claim"),
    ("double_signal", "double_signal-samecompany"),
    ("weak finance_grade", "weak-finance-grade"),
    ("stale lead", "stale-used"),
    ("only", "gift-under-3"),
    ("bare \"companies\"", "bare-companies-subject"),
    ("dollar amount", "dollar-stripped"),
]


def _bucket(flag: str) -> str:
    for needle, name in _FLAG_BUCKETS:
        if needle in flag:
            return name
    return "other"


def print_report(results: list[dict[str, Any]]) -> None:
    n = len(results)
    ok = [r for r in results if r["status"] == "ok"]
    no_gift = [r for r in results if r["status"] == "no_gift"]
    errors = [r for r in results if r["status"] == "error"]

    def dist(label: str, counter: Counter) -> None:
        print(f"\n{label}:")
        for k, v in counter.most_common():
            print(f"    {str(k):26} {v:3}  ({100*v//max(1,sum(counter.values()))}%)")

    print("\n" + "#" * 76)
    print(f"# TUNING REPORT — {n} prospects: {len(ok)} card(s), {len(no_gift)} no-gift, {len(errors)} error(s)")
    print("#" * 76)

    dist("Classification", Counter(r["classification"] for r in results))
    dist("Niche (mapped)", Counter(_niche(r) for r in ok if r.get("match_param")))
    dist("Gift size", Counter(r["gift_size"] for r in ok))
    dist("Geo level", Counter(r["geo"] for r in ok))
    dist("Subject shape", Counter(r["shape"] for r in ok))
    dist("Best-lead signal", Counter(r["best_signal"] for r in ok))

    flag_counter: Counter = Counter()
    for r in ok:
        for f in r["flags"]:
            flag_counter[_bucket(f)] += 1
    print("\nFlag frequency (across cards):")
    for k, v in flag_counter.most_common():
        print(f"    {k:28} {v:3}  ({100*v//max(1,len(ok))}% of cards)")

    unmapped = [r["niche_phrase"] for r in results
                if r["classification"] == "generalist" and r.get("niche_phrase")]
    if unmapped:
        print("\nUnmapped niches (stated but no taxonomy match — candidates to add):")
        for phrase in unmapped:
            print(f"    · {phrase}")

    if no_gift:
        print("\nNO GIFT (0 leads matched — usually missing city/state):")
        for r in no_gift:
            print(f"    · {r['firm']}")
    if errors:
        print("\nERRORS:")
        for r in errors:
            print(f"    · {r['firm']}: {r['error']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="M4 review cards / tuning report (sends nothing).")
    ap.add_argument("--limit", type=int, default=None, help="max prospects (default: all)")
    ap.add_argument("--csv", type=str, default=None, help="Apollo CSV path; first --limit rows")
    ap.add_argument("--summary", action="store_true", help="compact lines + aggregate tuning report")
    ap.add_argument("--delay", type=float, default=0.0,
                    help="seconds to pause between prospects (snapshot mode makes this unnecessary)")
    ap.add_argument("--leads-file", type=str, default=None,
                    help="use a local inventory.json instead of the live /api/leads")
    args = ap.parse_args()
    limit = args.limit if args.limit is not None else 10_000

    config.require("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID", "OPENAI_API_KEY")
    at = AirtableClient()
    print(f"[schema] ensure_schema (additive/idempotent): {at.ensure_schema()}")

    results: list[dict[str, Any]] = []
    if args.leads_file:
        # Local inventory (e.g. a re-processed batch) + live taxonomy (static).
        print(f"[snapshot] loading local inventory: {args.leads_file}")
        taxonomy = ScraperClient().niches()
        sc = SnapshotScraper.from_inventory_file(args.leads_file, taxonomy)
    else:
        # Snapshot the whole inventory up front (2 API calls while the scraper
        # is healthy), then filter in memory — no per-prospect calls.
        print("[snapshot] fetching full lead inventory...")
        sc = SnapshotScraper.fetch(max_attempts=5, backoff_base_s=1.0)
    with sc:
        taxonomy = sc.niches()
        print(f"[snapshot] {len(sc._all)} leads cached; {len(taxonomy)} taxonomy parents")
        prospects = load_from_csv(at, args.csv, limit) if args.csv else load_prospects(at, limit)
        if not prospects:
            print("No prospects. Add rows with a website, or edit SAMPLE_PROSPECTS.")
            at.close()
            return
        print(f"[run] {len(prospects)} prospect(s), {args.delay}s between each...\n")
        today = date.today()
        for i, row in enumerate(prospects):
            if i and args.delay:
                time.sleep(args.delay)      # let the scraper breathe between prospects
            try:
                r = process_one(at, sc, taxonomy, row, today)
            except Exception as exc:
                r = {"firm": row.get("firm_name"), "status": "error", "error": repr(exc), "flags": []}
            results.append(r)
            (print_compact if args.summary else print_full)(r)

    at.close()
    if args.summary:
        print_report(results)
    print("\n" + "=" * 76)
    print("DONE. Nothing was sent. Every card is review_status=pending — you approve by hand.")


if __name__ == "__main__":
    main()
