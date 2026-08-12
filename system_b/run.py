"""The whole platform in one command: Apollo CSV in → review CSV out.

    system_b/.venv/bin/python -m system_b.run \
        --in apollo-contacts-export.csv --out sequences.csv --pack cfo

For each prospect it researches the site, builds a gift from the lead platform's
`<pack>` inventory, and writes the full sequence for BOTH channels. One row per
prospect:

    email, first_name, last_name, company, linkedin_url,
    subject, email_1, email_2, email_3,
    li_dm_1, li_dm_1_evergreen, li_dm_2

Build the Smartlead sequence with 3 steps whose bodies are just {{email_1}},
{{email_2}}, {{email_3}}; add your signature + the CAN-SPAM footer ONCE in the
sequence editor. Follow-ups thread off email 1 (blank subject). The `li_*`
columns are pasted by hand on LinkedIn — nothing here can send either channel.

Rows come out most-personalized first, because the operator works the file down
and stops at LinkedIn's daily connection cap: row order decides who gets the
second channel.

Two companion files land next to the CSV:
  * `<out>.review.json` — the evidence behind every sequence (see review/).
  * `<out>.new.csv`     — only prospects no earlier run has sequenced, ready to
                          paste onto the bottom of the outreach history sheet.
                          Backed by `--ledger`, a flat list of every email ever
                          written. It holds no status: who accepted and who
                          replied stays in the sheet, where a human edits it and
                          no tool can race them.

Nothing is ever sent — this only writes spreadsheets for you to review.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from system_b import config
from system_b.clients.inventory import VALID_NICHES, load_taxonomy, snapshot_for_niche
from system_b.prospects import read_apollo_csv
from system_b.sequence import generate_sequence

# One row per prospect, carrying BOTH channels. Smartlead reads the columns it
# maps and ignores the rest, so a single file is also the row you paste into the
# outreach history sheet — one artifact instead of two that drift apart.
COLUMNS = [
    "email", "first_name", "last_name", "company", "linkedin_url",
    "subject", "email_1", "email_2", "email_3",
    "li_dm_1", "li_dm_1_evergreen", "li_dm_2",
]

# Every prospect ever written, so a later run can tell a genuinely new person
# from one an overlapping Apollo pull has already sequenced. A flat email list,
# NOT a status record: this file never learns whether anyone accepted or
# replied, which stays where a human can edit it without a tool racing them.
DEFAULT_LEDGER = Path(__file__).resolve().parent / "data" / "seen-prospects.csv"


def _review_path(out_path: str) -> Path:
    """Companion review-JSON path next to the CSV: `sequences.csv` ->
    `sequences.review.json` (any other suffix just gets `.review.json` appended)."""
    p = Path(out_path)
    stem = p.name[: -len(p.suffix)] if p.suffix else p.name
    return p.with_name(f"{stem}.review.json")


def _new_rows_path(out_path: str) -> Path:
    """`sequences.csv` -> `sequences.new.csv`."""
    p = Path(out_path)
    stem = p.name[: -len(p.suffix)] if p.suffix else p.name
    return p.with_name(f"{stem}.new.csv")


def _load_ledger(path: Path) -> set[str]:
    """The lowercased emails already sequenced by any previous run. Missing or
    unreadable ledger -> empty set: dedup is an optimization, and losing it must
    never stop a run from producing its CSV."""
    if not path.exists():
        return set()
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return {
                (r.get("email") or "").strip().lower()
                for r in csv.DictReader(fh)
                if (r.get("email") or "").strip()
            }
    except OSError:
        print(f"[ledger] could not read {path} — treating every prospect as new")
        return set()


def _append_ledger(path: Path, emails: list[str], today: date) -> None:
    """Append today's genuinely-new emails, with the date first seen. Append-only
    and header-on-create, so nothing this tool writes can clobber earlier rows."""
    if not emails:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if is_new_file:
            w.writerow(["email", "first_seen"])
        for email in emails:
            w.writerow([email, today.isoformat()])


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an outreach sequence per prospect from an Apollo CSV.")
    ap.add_argument("--in", dest="in_path", required=True, help="Apollo contacts export CSV")
    ap.add_argument("--out", dest="out_path", default="sequences.csv", help="output CSV")
    ap.add_argument("--pack", default="cfo", choices=sorted(VALID_NICHES),
                    help="niche pack for the whole run (voice + which gifts fit)")
    ap.add_argument("--review-out", dest="review_out", default=None,
                    help="review-gate JSON path (default: <out> with a .review.json suffix)")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                    help="every prospect ever sequenced, so <out>.new.csv holds only "
                         "the ones an earlier run has not already covered "
                         f"(default: {DEFAULT_LEDGER})")
    args = ap.parse_args()

    config.require("OPENAI_API_KEY")
    today = date.today()

    prospects = read_apollo_csv(args.in_path)
    print(f"[run] {len(prospects)} prospect(s) from {args.in_path} · pack={args.pack}")

    taxonomy = load_taxonomy()
    scraper = snapshot_for_niche(args.pack, today=today)

    results: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for p in prospects:
        firm = p.get("firm_name", "?")
        try:
            res = generate_sequence(p, scraper, taxonomy, today, pack_key=args.pack)
        except Exception as exc:  # noqa: BLE001 — surface, never abort the run
            print(f"  · {firm:32} error: {exc!r}")
            skipped.append((firm, f"error: {exc!r}"))
            continue
        if res.get("status") != "ok":
            print(f"  · {firm:32} {res.get('status')}")
            skipped.append((firm, res.get("status", "?")))
            continue
        results.append(res)
        print(f"  · {res['company']:32} ok ({res.get('gift_size')} in gift)")

    # Most-personalized first, matching the review gate's own order (it sorts the
    # same way client-side). The operator works the top of this file down and
    # stops at the LinkedIn daily cap, so row order decides WHICH prospects get
    # the second channel — alphabetical-by-company handed that to the letter A.
    # Company name breaks ties so the order is stable run to run.
    results.sort(key=lambda r: (
        ((r.get("review") or {}).get("personalization") or {}).get("rank", 99),
        (r.get("company") or "").lower(),
    ))

    with open(args.out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows({c: res.get(c, "") for c in COLUMNS} for res in results)

    # Companion review JSON: the full evidence + editable copy the review gate
    # (system_b.review.serve) renders. The CSV above stays the send artifact.
    review_path = Path(args.review_out) if args.review_out else _review_path(args.out_path)
    review_doc = {
        "pack": args.pack,
        "generated_at": today.isoformat(),
        "valid_count": len(results),
        "skipped": [{"firm": firm, "reason": why} for firm, why in skipped],
        "prospects": [res["review"] for res in results if res.get("review")],
    }
    review_path.write_text(json.dumps(review_doc, indent=2), encoding="utf-8")

    # New-prospects-only companion, for pasting onto the bottom of the outreach
    # history sheet. Written as a SEPARATE file rather than by editing the sheet:
    # the sheet is hand-maintained (accepted / replied live there), and a tool
    # that rewrites a file a human has open is a tool that eventually eats a
    # month of status.
    ledger_path = Path(args.ledger)
    seen = _load_ledger(ledger_path)
    fresh = [r for r in results if (r.get("email") or "").strip().lower() not in seen]
    new_rows_path = _new_rows_path(args.out_path)
    with open(new_rows_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows({c: res.get(c, "") for c in COLUMNS} for res in fresh)
    _append_ledger(
        ledger_path, [(r.get("email") or "").strip().lower() for r in fresh], today
    )

    print(f"\n[done] wrote {len(results)} sequence(s) to {args.out_path}")
    repeats = len(results) - len(fresh)
    print(f"[new] {len(fresh)} new prospect(s) -> {new_rows_path}"
          + (f"  ({repeats} already sequenced in an earlier run)" if repeats else ""))
    print(f"[review] wrote {review_path}  ·  review with: "
          f"system_b/.venv/bin/python -m system_b.review.serve --review {review_path}")
    if skipped:
        print(f"[skipped] {len(skipped)} prospect(s) got no sequence:")
        for firm, why in skipped:
            print(f"  · {firm}  ({why})")


if __name__ == "__main__":
    main()
