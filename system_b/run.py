"""The whole platform in one command: Apollo CSV in → review CSV out.

    system_b/.venv/bin/python -m system_b.run \
        --in apollo-contacts-export.csv --out sequences.csv --pack cfo

For each prospect it researches the site, builds a gift from the lead platform's
`<pack>` inventory, and writes the full 3-email sequence. The output CSV is what
you upload to Smartlead (one row per prospect):

    email, first_name, company, subject, email_1, email_2, email_3

Build the Smartlead sequence with 3 steps whose bodies are just {{email_1}},
{{email_2}}, {{email_3}}; add your signature + the CAN-SPAM footer ONCE in the
sequence editor. Follow-ups thread off email 1 (blank subject).

Nothing is ever sent — this only writes a spreadsheet for you to review.
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

COLUMNS = ["email", "first_name", "company", "subject", "email_1", "email_2", "email_3"]


def _review_path(out_path: str) -> Path:
    """Companion review-JSON path next to the CSV: `sequences.csv` ->
    `sequences.review.json` (any other suffix just gets `.review.json` appended)."""
    p = Path(out_path)
    stem = p.name[: -len(p.suffix)] if p.suffix else p.name
    return p.with_name(f"{stem}.review.json")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an outreach sequence per prospect from an Apollo CSV.")
    ap.add_argument("--in", dest="in_path", required=True, help="Apollo contacts export CSV")
    ap.add_argument("--out", dest="out_path", default="sequences.csv", help="output CSV")
    ap.add_argument("--pack", default="cfo", choices=sorted(VALID_NICHES),
                    help="niche pack for the whole run (voice + which gifts fit)")
    ap.add_argument("--review-out", dest="review_out", default=None,
                    help="review-gate JSON path (default: <out> with a .review.json suffix)")
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

    results.sort(key=lambda r: (r.get("company") or "").lower())

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

    print(f"\n[done] wrote {len(results)} sequence(s) to {args.out_path}")
    print(f"[review] wrote {review_path}  ·  review with: "
          f"system_b/.venv/bin/python -m system_b.review.serve --review {review_path}")
    if skipped:
        print(f"[skipped] {len(skipped)} prospect(s) got no sequence:")
        for firm, why in skipped:
            print(f"  · {firm}  ({why})")


if __name__ == "__main__":
    main()
