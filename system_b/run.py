"""The whole platform in one command: Apollo CSV in → review CSV out.

    system_b/.venv/bin/python -m system_b.run \
        --in apollo-contacts-export.csv --out sequences.csv --pack cfo

For each prospect it researches the site, builds a gift from the lead platform's
`<pack>` inventory, and writes the full sequence for BOTH channels. One row per
prospect:

    pack, cohort_date, email, first_name, last_name, company, linkedin_url,
    subject, email_1, email_2, email_3,
    li_dm_1, li_dm_1_evergreen, li_dm_2

Build the Smartlead sequence with 3 steps whose bodies are just {{email_1}},
{{email_2}}, {{email_3}}; add your signature + the CAN-SPAM footer ONCE in the
sequence editor. Follow-ups thread off email 1 (blank subject). The `li_*`
columns are pasted by hand on LinkedIn — nothing here can send either channel.

Rows come out most-personalized first, because the operator works the file down
and stops at LinkedIn's daily connection cap: row order decides who gets the
second channel.

Only NEW prospects are processed. `--ledger` records every email ever
sequenced, and the next run drops those people before it fetches a site or calls
a model — so the review gate always holds exactly the sequences you have not seen
yet, and nobody is reviewed or pasted into the history sheet twice. Pass
`--ignore-ledger` to re-run a fixed list while iterating on copy.

The ledger holds NO status. Who accepted and who replied lives in the history
sheet, which a human edits and no tool writes to.

`<out>.review.json` lands next to the CSV with the evidence behind every
sequence. Review it, edit what needs it, and the gate's Download CSV is the file
that goes BOTH to the sequencer and into the history sheet — it is the only one
carrying your edits and your removals.

Nothing is ever sent — this only writes spreadsheets for you to review.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

from system_b import config
from system_b.clients.inventory import (
    VALID_NICHES,
    load_taxonomy,
    snapshot_all_magnets,
    snapshot_for_niche,
)
from system_b.copy.names import NameFixer
from system_b.copy.naturalness import check_naturalness
from system_b.gift.allocation import DEFAULT_PATH as ALLOCATIONS_PATH
from system_b.gift.allocation import Allocations
from system_b.prospects import read_apollo_csv
from system_b.sequence import generate_sequence

# One row per prospect, carrying BOTH channels. Smartlead reads the columns it
# maps and ignores the rest, so a single file is also the row you paste into the
# outreach history sheet — one artifact instead of two that drift apart.
COLUMNS = [
    # `pack` and `cohort_date` lead because they are what the history sheet is
    # filtered and dated by: which campaign a row belongs to, and the day email 1
    # went out (every LinkedIn step is that date plus an offset).
    "pack", "cohort_date",
    "email", "first_name", "last_name", "company", "linkedin_url",
    "subject", "email_1", "email_2", "email_3",
    "li_dm_1", "li_dm_1_evergreen", "li_dm_2",
]

# Every prospect ever written, so a later run can tell a genuinely new person
# from one an overlapping Apollo pull has already sequenced. A flat email list,
# NOT a status record: this file never learns whether anyone accepted or
# replied, which stays where a human can edit it without a tool racing them.
DEFAULT_LEDGER = Path(__file__).resolve().parent / "data" / "seen-prospects.csv"

# The outreach history sheet: one row per prospect ever sequenced, filled by
# PASTING the review gate's LinkedIn CSV under the header each morning.
#
# It carries NO email copy. The email is in the sequencer within the hour and is
# never read from here again; the LinkedIn copy is read WEEKS later, when someone
# finally accepts a connection request and you need the message written for them.
# Storing both would double the width of a sheet whose only job is that lookup.
#
# Generated columns first (identical to LINKEDIN_COLUMNS, so a paste lands
# exactly under them), hand-kept status columns to their right, where a paste
# never reaches.
#
# The tool creates this file once and then never touches it again. Everything to
# the right of the generated block is the answer to a question only the operator
# can answer, and a writer that came back later to "update" a row is how a month
# of that gets lost.
_STATUS_COLUMNS = [
    "connect_sent",     # date the connection request went out
    "accepted",         # date they accepted (blank = still pending)
    "dm1_sent",         # date DM #1 went out; use the evergreen text past ~3 weeks
    "dm2_sent",         # date DM #2 went out (dm1_sent + 3)
    "replied_channel",  # email | linkedin — stop every channel the moment this is set
    "replied_date",
    "status",           # free text: booked, not interested, bounced, ...
]
# What the gate's LinkedIn export writes, in order. Mirrors LINKEDIN_COLUMNS in
# review/page.html; a test pins the two together.
LINKEDIN_COLUMNS = [
    "pack", "cohort_date",
    "email", "first_name", "last_name", "company", "linkedin_url",
    "li_dm_1", "li_dm_1_evergreen", "li_dm_2",
]
HISTORY_COLUMNS = [*LINKEDIN_COLUMNS, *_STATUS_COLUMNS]
DEFAULT_HISTORY = Path(__file__).resolve().parent / "data" / "outreach-history.csv"


def init_history(path: Path) -> bool:
    """Create the history sheet with just its header. Returns False (and touches
    nothing) when the file already exists — this is the one file the operator
    owns, so re-running the command must never blank a populated sheet."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(HISTORY_COLUMNS)
    return True


def _review_path(out_path: str) -> Path:
    """Companion review-JSON path next to the CSV: `sequences.csv` ->
    `sequences.review.json` (any other suffix just gets `.review.json` appended)."""
    p = Path(out_path)
    stem = p.name[: -len(p.suffix)] if p.suffix else p.name
    return p.with_name(f"{stem}.review.json")


def _location_only(res: dict) -> bool:
    """A draft whose gift matched the firm on place alone, not industry."""
    # `niche` is the industry the email claims; None when it claims a place.
    return not (res.get("review") or {}).get("niche")


def _check_ledger_header(path: Path) -> None:
    """Refuse a ledger whose columns are not this file's columns.

    Checked at LOAD, before any work, because the damage is done by then: the
    wrong file yields the wrong dedup set and the batch is built against it.
    `morning.py` had `--ledger` pointed at outreach-history.csv -- which starts
    `pack,cohort_date,email,...` -- so `_append_ledger` wrote its two columns
    positionally, every address landed under `pack`, and `_load_ledger` (which
    reads `email`) saw none of them. Dedup was off for 20 prospects, and the
    run reported "skipping 30" against a file holding 50 rows.

    Loud, not lenient. Every other failure here costs a wasted run; this one
    emails a real person twice.
    """
    if not path.exists():
        return
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            header = next(csv.reader(fh), [])
    except OSError:
        # Unreadable is the existing degrade-to-empty case and stays that way:
        # dedup is an optimization and losing it must not stop a run. Only a
        # READABLE file with the wrong columns is the dangerous case, because
        # that one silently produces a wrong dedup set rather than none.
        return
    if header and [h.strip().lower() for h in header] != LEDGER_COLUMNS:
        raise SystemExit(
            f"[ledger] {path} has columns {header}, expected {LEDGER_COLUMNS}.\n"
            "         That looks like the history sheet, not the dedup ledger. "
            "Using it would\n"
            "         silently disable dedup and re-email people. Point "
            "--ledger at\n         data/seen-prospects.csv."
        )


def _load_ledger(path: Path) -> set[str]:
    """The lowercased emails already sequenced by any previous run. Missing or
    unreadable ledger -> empty set: dedup is an optimization, and losing it must
    never stop a run from producing its CSV."""
    if not path.exists():
        return set()
    _check_ledger_header(path)
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


LEDGER_COLUMNS = ["email", "first_seen"]


def _append_ledger(path: Path, emails: list[str], today: date) -> None:
    """Append today's genuinely-new emails, with the date first seen. Append-only
    and header-on-create, so nothing this tool writes can clobber earlier rows.

    Refuses a file whose header is not this file's header. `morning.py` had
    `--ledger` pointed at outreach-history.csv, which starts `pack,cohort_date,
    email,...`; these two columns were appended positionally, so every address
    landed under `pack`, `email` stayed blank, and `_load_ledger` -- which reads
    `email` -- saw none of them. Dedup was off for 20 prospects and nothing
    raised. Writing the wrong file is the one failure here that emails a real
    person twice, so it is worth being loud about.
    """
    if not emails:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _check_ledger_header(path)
    is_new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if is_new_file:
            w.writerow(LEDGER_COLUMNS)
        for email in emails:
            w.writerow([email, today.isoformat()])


# Share of drafted firms whose site names no rung above which the problem is
# almost certainly the prospect list rather than their websites.
NO_RUNG_ALARM = 0.20

BACKLOG_COLUMNS = [
    "reason", "firm_name", "first_name", "email", "website", "linkedin",
    "city", "state", "stated_vertical", "stated_phrase", "all_stated_phrases",
]


def write_backlog(rows: list[dict], out_path: Path) -> Path | None:
    """Prospects held because no gift could be built, written beside the CSV.

    These are not failures and must not be thrown away. A firm that serves
    construction is a perfectly good prospect; there is simply no construction
    magnet yet. Grouped by `reason`, this file is the demand side telling you
    which magnet to build next — and when one is built, the list of who to send
    it to is already sitting here.
    """
    if not rows:
        return None
    path = out_path.with_name(f"{out_path.stem}.backlog.csv")
    order = {"no_magnet": 0, "inventory_dry": 1, "no_vertical": 2}
    rows = sorted(rows, key=lambda r: (order.get(r["reason"], 9),
                                       r.get("stated_vertical", ""),
                                       r.get("firm_name", "")))
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BACKLOG_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate an outreach sequence per prospect from an Apollo CSV.")
    # Not `required`: --init-history is a standalone setup command with no input
    # CSV. Enforced below instead, so the missing-argument error still fires for
    # a normal run.
    ap.add_argument("--in", dest="in_path", help="Apollo contacts export CSV")
    ap.add_argument("--out", dest="out_path", default="sequences.csv", help="output CSV")
    ap.add_argument("--force-pack", action="store_true",
                    help="use --pack for EVERY prospect instead of their site's "
                         "rung, their Apollo list, or the neutral voice")
    ap.add_argument("--legacy-niche", action="store_true",
                    help="load the old per-niche job-post inventory instead of "
                         "the vertical magnets (mssp/msp/cloud still use it)")
    ap.add_argument("--pack", default="cfo", choices=sorted(VALID_NICHES),
                    help="the voice for every prospect with --force-pack (and the IT "
                         "packs' inventory with --legacy-niche); otherwise each "
                         "prospect's voice is chosen per firm (choose_voice)")
    ap.add_argument("--review-out", dest="review_out", default=None,
                    help="review-gate JSON path (default: <out> with a .review.json suffix)")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                    help="every prospect ever sequenced; the next run skips them "
                         f"before doing any work (default: {DEFAULT_LEDGER})")
    ap.add_argument("--allocations", default=str(ALLOCATIONS_PATH),
                    help="a log of which firm got which organization; since "
                         "2026-10-25 it no longer blocks a lead from other firms")
    ap.add_argument("--skip-name-fixer", action="store_true",
                    help="print lead names as the registry wrote them (no model)")
    ap.add_argument("--skip-naturalness", action="store_true",
                    help="skip the advisory read that flags phrases which do not "
                         "sound like a person wrote them. One extra model call per "
                         "prospect; it never edits copy, only points at spans.")
    ap.add_argument("--ignore-ledger", action="store_true",
                    help="re-sequence prospects an earlier run already covered, and "
                         "do NOT record this run. For iterating on copy against a "
                         "fixed list: without it, a second run of the same export "
                         "produces nothing, because everyone in it is already done.")
    ap.add_argument("--target", type=int, default=0,
                    help="stop once this many VALID sequences exist, walking the "
                         "input in order (0 = process every row). Skipped prospects "
                         "do not count, so `--target 30` means 30 rows on the review "
                         "gate, not 30 rows read. Every prospect costs a site fetch "
                         "and LLM calls, so this is also what stops a 200-row export "
                         "from being paid for in full.")
    ap.add_argument("--init-history", action="store_true",
                    help="create the outreach history sheet (header only) and exit. "
                         "Safe to re-run: it refuses to touch an existing file.")
    ap.add_argument("--history", default=str(DEFAULT_HISTORY),
                    help=f"path for --init-history (default: {DEFAULT_HISTORY})")
    args = ap.parse_args()

    if args.init_history:
        path = Path(args.history)
        if init_history(path):
            print(f"[history] created {path}")
            print(f"[history] {len(HISTORY_COLUMNS)} columns: "
                  f"{len(LINKEDIN_COLUMNS)} generated (paste the gate's LinkedIn CSV under them) "
                  f"+ {len(_STATUS_COLUMNS)} you keep by hand")
        else:
            print(f"[history] {path} already exists — left untouched")
        return

    if not args.in_path:
        ap.error("--in is required (or pass --init-history to set up the sheet)")

    config.require("OPENAI_API_KEY")
    today = date.today()

    prospects = read_apollo_csv(args.in_path)
    print(f"[run] {len(prospects)} prospect(s) from {args.in_path} · pack={args.pack}")

    # Drop anyone an earlier run already sequenced, BEFORE the expensive part.
    # Every prospect past this line costs a site fetch and several LLM calls, and
    # a re-sequenced person is worse than wasted money: they would reach the
    # review gate, be reviewed again, and be pasted into the history sheet twice.
    if args.ignore_ledger:
        print("[ledger] --ignore-ledger: no filtering, and this run is not recorded")
    else:
        seen = _load_ledger(Path(args.ledger))
        kept = [p for p in prospects if (p.get("email") or "").strip().lower() not in seen]
        if len(kept) != len(prospects):
            print(f"[ledger] skipping {len(prospects) - len(kept)} prospect(s) "
                  "sequenced in an earlier run")
        prospects = kept

    taxonomy = load_taxonomy()
    # The lead inventory is the three VERTICAL magnets (nonprofit / funds /
    # ecommerce), not one per-niche job-post file. `--pack` still selects the
    # copy VOICE (which rung of finance service the prospect sells); the
    # vertical selects which leads they can be shown at all. `--legacy-niche`
    # restores the old per-niche load for the IT packs, which still run off the
    # breach + IT job inventory.
    if args.legacy_niche:
        scraper = snapshot_for_niche(args.pack, today=today)
    else:
        scraper = snapshot_all_magnets(today=today)

    target = args.target if args.target > 0 else None
    if target:
        print(f"[run] target {target} valid sequence(s) — stopping as soon as they land")

    naturalness = None if args.skip_naturalness else check_naturalness
    # A model tidies lead names behind a code guard (copy/names.py).
    name_fixer = None if args.skip_name_fixer else NameFixer()
    if naturalness is None:
        print("[run] --skip-naturalness: no advisory copy read")

    # A LOG of which firm got which organization, nothing more. Until
    # 2026-10-25 a lead handed to one firm was off limits to every other firm
    # in its state; the user dropped that rule ("we are not big enough where
    # prospects will compare notes"), so every firm gets the strongest leads
    # near it. A firm's own sequence still never repeats an organization.
    allocations = Allocations.load(Path(args.allocations))

    results: list[dict] = []
    # Firms matched only on location (their site names no industry we have
    # leads for) are drafted LAST: held here and used only when the export
    # runs out of industry matches before the target. Their gift is true but
    # beside their work (a restaurant accountant shown charities), so 5 of 20
    # such emails in one batch (2026-10-25) spent a fifth of the day on the
    # weakest drafts. A held one is not on the ledger, so it is retried later.
    location_only: list[tuple[dict, dict]] = []
    skipped: list[tuple[str, str]] = []
    backlog: list[dict] = []
    for p in prospects:
        if target is not None and len(results) >= target:
            break
        firm = p.get("firm_name", "?")
        try:
            res = generate_sequence(p, scraper, taxonomy, today, pack_key=args.pack,
                                    force_pack=args.force_pack,
                                    naturalness=naturalness, name_fixer=name_fixer)
        except Exception as exc:  # noqa: BLE001 — surface, never abort the run
            print(f"  · {firm:32} error: {exc!r}")
            skipped.append((firm, f"error: {exc!r}"))
            continue
        if res.get("status") != "ok":
            row_backlog = res.get("backlog")
            if row_backlog:
                backlog.append(row_backlog)
                print(f"  · {firm:32} held: {row_backlog['reason']}"
                      + (f" ({row_backlog['stated_vertical']})"
                         if row_backlog.get("stated_vertical") else ""))
            else:
                print(f"  · {firm:32} {res.get('status')}")
            skipped.append((firm, res.get("status", "?")))
            continue
        if target is not None and _location_only(res):
            location_only.append((p, res))
            print(f"  · {firm:32} location-only match, drafted only if the target needs it")
            continue
        results.append(res)
        allocations.record(res.get("lead_identities") or [], firm, p.get("state"), today)
        print(f"  · {res['company']:32} ok ({res.get('gift_size')} in gift, "
              f"voice: {res.get('pack', '?')} from {res.get('voice_source', '?')})")

    # Fill what the industry matches left, in file order.
    for p, res in location_only:
        if target is not None and len(results) >= target:
            break
        firm = p.get("firm_name", "?")
        results.append(res)
        allocations.record(res.get("lead_identities") or [], firm, p.get("state"), today)
        print(f"  · {res['company']:32} ok, location-only ({res.get('gift_size')} in gift)")

    # A HEALTH SIGNAL, not a per-prospect fact. Every firm in this campaign is
    # supposed to sell one of the three finance services; a handful of
    # unreadable sites is normal, but a large share whose site names none means
    # the PROSPECT LIST is wrong: an Apollo pull that swept in consultancies and
    # IT shops rather than finance practices. Such firms are no longer held
    # (their Apollo list or the neutral voice speaks for them), so the count is
    # of drafted rows whose voice did not come from their own site.
    unread = sum(1 for r in results if r.get("voice_source") in ("apollo list", "neutral"))
    if results and unread / len(results) > NO_RUNG_ALARM:
        print(f"\n[!] {unread} of {len(results)} drafted firms "
              f"({100*unread/len(results):.0f}%) name none of bookkeeping, "
              "accounting or CFO work on their own website.")
        print("    Above ~20% that is usually the LIST, not the sites; "
              "check the Apollo filters brought back finance firms.")

    if target is not None and len(results) < target:
        print(f"[run] input exhausted at {len(results)} of {target} — "
              "the export ran out before the target did")

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

    # Record what was sequenced, so tomorrow's run skips these people at the door.
    # Only VALID results: a prospect the inventory could not gift was never
    # contacted, so it should be retried once the leads move.
    if not args.ignore_ledger:
        _append_ledger(
            Path(args.ledger),
            [(r.get("email") or "").strip().lower() for r in results],
            today,
        )
        # Same rule as the prospect ledger: a run that records nothing for
        # prospects (iterating on copy) holds no organizations either.
        n = allocations.save(Path(args.allocations))
        if n:
            print(f"[allocations] {n} organization(s) recorded -> {args.allocations}")

    print(f"\n[done] wrote {len(results)} sequence(s) to {args.out_path}")
    print(f"[review] wrote {review_path}  ·  review with: "
          f"system_b/.venv/bin/python -m system_b.review.serve --review {review_path}")
    backlog_path = write_backlog(backlog, Path(args.out_path))
    if backlog_path:
        from collections import Counter as _Counter
        by_reason = _Counter(r["reason"] for r in backlog)
        print(f"\n[backlog] {len(backlog)} prospect(s) held -> {backlog_path}")
        for reason, n in by_reason.most_common():
            note = {
                "no_magnet": "serve a vertical we have no leads for — "
                             "this is the list that says what to build next",
                "no_vertical": "state no industry we could map — founder ask, not a gift",
                "inventory_dry": "right vertical, but no unused lead was left",
            }.get(reason, "")
            print(f"    {n:>4}  {reason:<14} {note}")
        verticals = _Counter(r["stated_vertical"] for r in backlog
                             if r["reason"] == "no_magnet" and r["stated_vertical"])
        if verticals:
            print("    verticals worth a magnet, by demand:")
            for v, n in verticals.most_common(8):
                print(f"       {n:>4}  {v}")

    if skipped:
        print(f"[skipped] {len(skipped)} prospect(s) got no sequence:")
        for firm, why in skipped:
            print(f"  · {firm}  ({why})")


if __name__ == "__main__":
    main()
