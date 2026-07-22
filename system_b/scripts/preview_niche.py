"""Offline per-niche preview / verification.

For each niche, build the gift + Email #1 from a LOCAL leadgen inventory and
print them — no OpenAI, no Airtable, no live site. Exercises the
inventory -> gift -> copy path (the geo/generalist branch) so you can eyeball
each niche's copy against real leads.

    LEADGEN_INVENTORY_DIR=../lead-platform/leadgen/data \
        python -m system_b.scripts.preview_niche --state CA
    # or a single niche:
        python -m system_b.scripts.preview_niche --niche mssp --state CA

Run from the repo ROOT (running inside system_b/ shadows stdlib `copy`).
"""

from __future__ import annotations

import argparse
from datetime import date

from system_b.clients.inventory import (
    VALID_NICHES,
    descriptions_for,
    snapshot_for_niche,
)
from system_b.copy.email import build_email_1
from system_b.gift.engine import build_gift
from system_b.gift.models import Prospect
from system_b.niches.base import pack_for


def preview(niche_key: str, *, city: str | None, state: str | None, today: date) -> None:
    pack = pack_for(niche_key)
    sc = snapshot_for_niche(niche_key, today=today)
    # A generalist prospect exercises the geo path (the niched path needs a live
    # site + LLM; this smoke stays offline).
    prospect = Prospect(
        firm_name="Preview Firm", city=city, state=state,
        classification="generalist", first_name="there",
    )
    gift = build_gift(prospect, sc, pack=pack)
    print(f"\n{'=' * 70}\n{niche_key.upper()}  (geo={city or ''}/{state or ''})")
    if gift is None:
        print("  no gift — inventory has no leads matching this geography")
        return
    draft = build_email_1(
        gift, prospect, descriptions_for(gift.leads),
        today=today, pack=pack, include_signoff=False,
    )
    print(f"  gift: {gift.gift_size} lead(s), geo_level={gift.geo_level}")
    for lead in gift.leads:
        print(f"    · {lead.company} [{lead.signal_type}] {lead.city},{lead.state}")
    print(f"\n  SUBJECT: {draft.subject}\n")
    print("  " + draft.body.replace("\n", "\n  "))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline per-niche gift+copy preview")
    ap.add_argument("--niche", choices=sorted(VALID_NICHES), default=None,
                    help="preview one niche (default: all five)")
    ap.add_argument("--city", default=None)
    ap.add_argument("--state", default=None, help="2-letter state to match on")
    args = ap.parse_args(argv)

    today = date.today()
    niches = [args.niche] if args.niche else sorted(VALID_NICHES)
    for n in niches:
        try:
            preview(n, city=args.city, state=args.state, today=today)
        except FileNotFoundError:
            print(f"\n{n.upper()}: no inventory file (set LEADGEN_INVENTORY_DIR)")
        except Exception as exc:  # noqa: BLE001 — a preview tool should not abort
            print(f"\n{n.upper()}: ERROR {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
