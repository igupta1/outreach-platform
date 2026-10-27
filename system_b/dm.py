"""One prospect, on demand: the LinkedIn connection note with the gift in it.

    # from the repo root
    system_b/.venv/bin/python -m system_b.dm --website acmecpa.com \\
        --first-name Jane --last-name Doe --company "Acme CPA" --city Denver --state CO

    # or paste their profile (copy it on LinkedIn first); flags still win
    pbpaste | system_b/.venv/bin/python -m system_b.dm --paste --website acmecpa.com

The same pipeline as the morning batch, for one firm: `generate_sequence`
researches their site, picks the voice, builds the gift behind Gates A and B,
and honours the allocation ledger (one organization per firm per state). What
it prints is the LinkedIn version of the sequence:

    connection note   the gift, <= 300 characters (copy.linkedin.build_connect_note)
    after they accept the email-2 text: one more lead of the same kind
    last touch        the email-3 text: what is actually draining their week

Nothing is sent and nothing touches LinkedIn: you paste the note yourself, and
no LinkedIn page is ever fetched (that needs a login and breaks their terms).
`--paste` only EXTRACTS name, firm and place from text you copied; no model
writes any part of the note.

Recorded unless `--dry-run`: the organizations used, in lead-allocations.csv
(so an email prospect in the same state is never shown them), and the run, in
data/linkedin-log.csv (gitignored). The email ledger is NOT touched: nobody
was emailed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from system_b.copy.linkedin import CONNECT_NOTE_MAX
from system_b.gift.allocation import DEFAULT_PATH as ALLOCATIONS_PATH
from system_b.gift.allocation import Allocations, _firm
from system_b.prospects import _normalize_website

DATA = Path(__file__).resolve().parent / "data"
LOG_PATH = DATA / "linkedin-log.csv"
LOG_COLUMNS = [
    "date", "first_name", "last_name", "company", "website", "city", "state",
    "pack", "niche", "connect_note", "dm_after_accept", "dm_last",
]
# Domains that say nothing about which firm an address belongs to.
_FREEMAIL = frozenset({"gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
                       "icloud.com", "aol.com", "me.com", "live.com", "msn.com"})

_EXTRACT_SYSTEM = (
    "You read text copied from a LinkedIn profile and pull out facts that are "
    "stated in it. Return JSON with keys first_name, last_name, company, city, "
    "state, website. company is the firm they CURRENTLY work at. state is the US "
    "state as written. website only if a URL or domain appears in the text. Use "
    "null for anything not stated; never guess."
)


def extract_profile(text: str, *, model: str = "gpt-4o-mini") -> dict[str, str | None]:
    """Name, firm and place from pasted profile text. Extraction only."""
    from openai import OpenAI

    from system_b import config

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _EXTRACT_SYSTEM},
                  {"role": "user", "content": text[:6000]}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    return {k: (str(data[k]).strip() or None) if data.get(k) else None
            for k in ("first_name", "last_name", "company", "city", "state", "website")}


def _domain(url_or_email: str) -> str:
    s = (url_or_email or "").strip().lower()
    s = s.rsplit("@", 1)[-1]
    s = re.sub(r"^[a-z]+://", "", s).split("/", 1)[0]
    return s.removeprefix("www.")


def already_contacted(website: str, company: str, *, data: Path = DATA,
                      allocations: Path = ALLOCATIONS_PATH,
                      log: Path = LOG_PATH) -> list[str]:
    """Where this firm already shows up. A warning, never a block: a lukewarm
    contact can be someone you also emailed, and that is your call to make."""
    found: list[str] = []
    dom, firm = _domain(website), _firm(company)

    def rows(path: Path):
        if not path.exists():
            return []
        try:
            with path.open(newline="", encoding="utf-8-sig") as fh:
                return list(csv.DictReader(fh))
        except (OSError, csv.Error):
            return []

    for name in ("seen-prospects.csv", "outreach-history.csv"):
        for r in rows(data / name):
            d = _domain(r.get("email") or "")
            if dom and d == dom and d not in _FREEMAIL:
                found.append(f"emailed already ({r.get('email')}, {name})")
                break
            if firm and _firm(r.get("company")) == firm:
                found.append(f"emailed already ({r.get('company')}, {name})")
                break
    if firm and any(_firm(r.get("firm")) == firm for r in rows(allocations)):
        found.append("already handed leads (lead-allocations.csv)")
    for r in rows(log):
        if (dom and _domain(r.get("website") or "") == dom) or \
                (firm and _firm(r.get("company")) == firm):
            found.append(f"already sent a LinkedIn note on {r.get('date')} "
                         f"({r.get('first_name')} {r.get('last_name')})")
            break
    return found


def append_log(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def _rule(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 60 - len(title)))


def main(argv: list[str] | None = None) -> int:
    from system_b.clients.inventory import VALID_NICHES

    ap = argparse.ArgumentParser(prog="dm", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--website", help="the firm's website (required, here or in the paste)")
    ap.add_argument("--first-name")
    ap.add_argument("--last-name")
    ap.add_argument("--company")
    ap.add_argument("--city")
    ap.add_argument("--state")
    ap.add_argument("--paste", action="store_true",
                    help="read copied LinkedIn profile text from stdin and pull "
                         "name / firm / place out of it (flags override it)")
    ap.add_argument("--pack", choices=sorted(VALID_NICHES), default="cfo",
                    help="force this voice (with --force-pack); otherwise their site decides")
    ap.add_argument("--force-pack", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="print only: record no allocation and no log row")
    ap.add_argument("--allocations", type=Path, default=ALLOCATIONS_PATH)
    ap.add_argument("--log", type=Path, default=LOG_PATH)
    a = ap.parse_args(argv)

    from system_b import morning

    # The same inventory the morning batch reads, never the retired blob.
    os.environ["LEADGEN_INVENTORY_DIR"] = str(morning.INVENTORY_DIR)
    os.environ["LEADGEN_BLOB_BASE_URL"] = ""

    fields = {"first_name": a.first_name, "last_name": a.last_name,
              "company": a.company, "city": a.city, "state": a.state,
              "website": a.website}
    if a.paste:
        if sys.stdin.isatty():
            print("paste the profile, then ctrl-d:")
        text = sys.stdin.read()
        if text.strip():
            pulled = extract_profile(text)
            for k, v in pulled.items():
                fields[k] = fields[k] or v

    website = _normalize_website(fields["website"] or "")
    if not website:
        ap.error("need the firm's website (--website): it is what the research reads")
    company = fields["company"] or _domain(website)

    _rule("prospect")
    name = " ".join(x for x in (fields["first_name"], fields["last_name"]) if x)
    place = ", ".join(x for x in (fields["city"], fields["state"]) if x)
    print(f"  {name or '(no name)'}  ·  {company}  ·  {place or '(no location)'}")
    print(f"  {website}")
    if not fields["state"]:
        print("  warn: no state, so no local leads and no allocation region")
    for w in already_contacted(website, company, allocations=a.allocations, log=a.log):
        print(f"  warn: {w}")

    problems, _ = morning.check()
    if problems:
        for p in problems:
            print(f"  STOP {p}")
        return 1

    from system_b import config
    from system_b.clients.inventory import load_taxonomy, snapshot_all_magnets
    from system_b.sequence import generate_sequence

    config.require("OPENAI_API_KEY")
    today = date.today()
    row = {"firm_name": company, "website": website, "city": fields["city"],
           "state": fields["state"], "first_name": fields["first_name"],
           "last_name": fields["last_name"], "email": "", "linkedin": "",
           "_source": ""}
    allocations = Allocations.load(a.allocations)
    row["blocked_identities"] = allocations.blocked(company, fields["state"])

    print("\n  researching their site and building the gift...")
    res = generate_sequence(row, snapshot_all_magnets(today=today), load_taxonomy(),
                            today, pack_key=a.pack, force_pack=a.force_pack,
                            naturalness=None)
    if res.get("status") != "ok":
        b = res.get("backlog") or {}
        print(f"\n  no gift: {b.get('reason') or res.get('status')}"
              + (f" ({b['stated_vertical']})" if b.get("stated_vertical") else ""))
        return 2

    review = res.get("review") or {}
    note = res.get("li_connect_note")
    niche = review.get("niche")
    print(f"  voice: {res.get('pack')} (from {res.get('voice_source')})  ·  "
          f"match: {('niche: ' + niche) if niche else 'location only, no industry claimed'}")

    _rule("connection note")
    if not note:
        print(f"  could not fit a lead in {CONNECT_NOTE_MAX} characters, so no note.")
        print("  (send a plain connection request and use the message below after they accept)")
    else:
        print(note)
        print(f"\n  [{len(note)}/{CONNECT_NOTE_MAX} characters]")
    _rule("check before pasting")
    for ld in review.get("leads") or []:
        if note and ld.get("company") and _named(ld["company"], note):
            print(f"  {ld['company']}: {ld.get('role')}")
            print(f"    {ld.get('source_url') or '(no link)'}")
    for f in review.get("flags") or []:
        print(f"  flag: {f}")

    _rule("after they accept (if no reply in ~3 days)")
    print(res.get("email_2") or "")
    _rule("last touch (~4 days later)")
    print(res.get("email_3") or "")

    if a.dry_run:
        print("\n  --dry-run: nothing recorded")
        return 0
    allocations.record(res.get("lead_identities") or [], company, fields["state"], today)
    n = allocations.save(a.allocations)
    append_log(a.log, {
        "date": today.isoformat(), "first_name": fields["first_name"] or "",
        "last_name": fields["last_name"] or "", "company": company,
        "website": website, "city": fields["city"] or "", "state": fields["state"] or "",
        "pack": res.get("pack") or "", "niche": niche or "",
        "connect_note": note or "", "dm_after_accept": res.get("email_2") or "",
        "dm_last": res.get("email_3") or "",
    })
    print(f"\n  recorded: {n} organization(s) -> {a.allocations.name}, "
          f"this note -> {a.log.name}")
    return 0


def _named(company: str, note: str) -> bool:
    """Is this lead in the note? The note prints the spoken name (no "Inc.")."""
    from system_b.copy.lex import spoken_name

    return spoken_name(company) in note


if __name__ == "__main__":
    sys.exit(main())
