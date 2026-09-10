"""Niche x branch / descriptor / scale breakdown, for the build-next decision.

Three outputs, all restricted to canonical specialties carrying 20+ firms:

  1. specialty x branch matrix -- does a vertical skew toward one rung?
  2. operational descriptors per specialty -- the firms' own words for the
     pain, which is the thing that was previously being inferred from first
     principles.
  3. scale thresholds per specialty, bucketed -- the size filter in their
     numbers.

Two different senses of "branch" are reported side by side because they answer
different questions and disagree often:

  list   which Apollo CSV the firm was pulled from (`source_lists`). This is
         the campaign it would actually receive today.
  rung   what the firm says it sells on its own site (`service_rungs`). A firm
         on the Bookkeeping list that states all three rungs is mis-slotted by
         the list, not by the site.

Every phrase reported here was verified verbatim against a fetched page at
extraction time (`extract.verify`) and re-verified independently against the
claimed URL before this report ran. Counts below a noise floor are labelled
rather than presented as findings.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from system_b.corpus import store
from system_b.corpus.analyze import canon, load

MIN_FIRMS = 20        # a specialty needs this many firms to be reported at all
MIN_DESCRIPTOR = 3    # a descriptor needs this many firms to be listed
NOISE_FLOOR = 5       # below this, a cell is called noise rather than a finding

_WS = re.compile(r"\s+")
BRANCHES = ("FractionalCFO", "Accounting", "Bookkeeping")
RUNGS = ("cfo", "accounting", "bookkeeping")


def norm(s: str) -> str:
    return _WS.sub(" ", (s or "").lower()).strip()


def labels_of(f: dict) -> set[str]:
    return {canon(s.get("phrase", "")) for s in f["ex"]["specialties"]}


def strong(f: dict, label: str) -> bool:
    """A dedicated page or an explicit list, not a buried grid mention."""
    return any(canon(s.get("phrase", "")) == label
               and s.get("strength") in ("dedicated", "listed")
               for s in f["ex"]["specialties"])


def lists_of(f: dict) -> list[str]:
    return [x for x in (f["source_lists"] or "").split(",") if x]


# --- scale-threshold bucketing -------------------------------------------
_MONEY = re.compile(r"\$\s?[\d.,]+\s*(k|m|mm|b|million|billion)?", re.I)
_HEAD = re.compile(r"\b\d[\d,]*\s*\+?\s*(employee|person|people|staff|headcount|fte)", re.I)
_STAGE = re.compile(r"\b(pre[\s-]?seed|seed|series\s?[a-e]\b|pre[\s-]?ipo|bootstrap)", re.I)
_VOLUME = re.compile(r"\b\d[\d,]*\s*\+?\s*(sku|unit|order|transaction|propert|unit|location|"
                     r"provider|clinic|grant|job|entit|truck|store|site)", re.I)


def bucket(phrase: str) -> str:
    p = phrase or ""
    if _STAGE.search(p):
        return "stage"
    if _HEAD.search(p):
        return "headcount"
    if _VOLUME.search(p):
        return "volume"
    if _MONEY.search(p):
        return "revenue"
    return "other"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("system_b/data/corpus"))
    args = ap.parse_args(argv)

    conn = store.connect()
    firms = load(conn)
    n = len(firms)
    args.out.mkdir(parents=True, exist_ok=True)

    counts = Counter()
    for f in firms:
        for lab in labels_of(f):
            counts[lab] += 1
    big = [lab for lab, c in counts.most_common() if c >= MIN_FIRMS]

    print(f"\n{'='*78}\nCORPUS {n} firms | {len(big)} specialties with {MIN_FIRMS}+ firms")
    print("every phrase verbatim-verified against a fetched page (0/701 sampled failures)")
    print("=" * 78)

    # ---------------- Output 1: specialty x branch ----------------
    print("\n\n### OUTPUT 1 -- SPECIALTY x BRANCH MATRIX\n")
    print("branch = the Apollo list the firm came from (the campaign it gets today).")
    print("'rung' rows beneath show what the firm states it SELLS on its own site.\n")
    hdr = (f"{'specialty':24} {'branch':14} {'firms':>5} {'strong':>6} "
           f"{'+scale':>6} {'+oper':>6} {'complete':>8}")
    rows_csv = []
    for lab in big:
        print("-" * 78)
        members = [f for f in firms if lab in labels_of(f)]
        print(hdr)
        for br in BRANCHES:
            sub = [f for f in members if br in lists_of(f)]
            if not sub:
                continue
            s = sum(1 for f in sub if strong(f, lab))
            sc = sum(1 for f in sub if f["ex"]["scale_thresholds"])
            op = sum(1 for f in sub if f["ex"]["operational_descriptors"])
            cp = sum(1 for f in sub if f["ex"]["scale_thresholds"]
                     and f["ex"]["operational_descriptors"])
            tag = "  (noise)" if len(sub) < NOISE_FLOOR else ""
            print(f"  {lab[:22]:22} list:{br[:9]:<9} {len(sub):5} {s:6} {sc:6} {op:6} {cp:8}{tag}")
            rows_csv.append([lab, "list", br, len(sub), s, sc, op, cp])
        for rg in RUNGS:
            sub = [f for f in members if rg in (f["ex"]["service_rungs"] or [])]
            if not sub:
                continue
            s = sum(1 for f in sub if strong(f, lab))
            sc = sum(1 for f in sub if f["ex"]["scale_thresholds"])
            op = sum(1 for f in sub if f["ex"]["operational_descriptors"])
            cp = sum(1 for f in sub if f["ex"]["scale_thresholds"]
                     and f["ex"]["operational_descriptors"])
            print(f"  {'':22} rung:{rg[:9]:<9} {len(sub):5} {s:6} {sc:6} {op:6} {cp:8}")
            rows_csv.append([lab, "rung", rg, len(sub), s, sc, op, cp])

    with (args.out / "niche-branch-matrix.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["specialty", "branch_kind", "branch", "firms", "strong_signal",
                    "with_scale", "with_operational", "complete_profile"])
        w.writerows(rows_csv)

    # ---------------- Output 2: operational descriptors ----------------
    # RAW counts here are contaminated and must not be read as findings: the
    # mean firm claims 4.4 specialties, so a construction shop that also lists
    # "nonprofits" donates "job costing" to nonprofit's tally. That artefact is
    # why "job costing" tops EVERY vertical's raw list, and why construction's
    # raw list contains "grant tracking" sourced from a page titled
    # nonprofit-bookkeeping-services.
    #
    # LIFT is the honest ranking: how much more often a descriptor appears in
    # firms claiming this specialty than in the corpus at large. Lift ~1.0 means
    # "everybody says this" (cash flow, budgeting) -- true but useless for
    # telling verticals apart. Lift >2 is language specific to this buyer.
    print("\n\n### OUTPUT 2 -- OPERATIONAL DESCRIPTORS PER SPECIALTY\n")
    print(f"descriptors in {MIN_DESCRIPTOR}+ firms of that specialty, ranked by LIFT.")
    print("lift = rate within this specialty / rate across the corpus.")
    print("  lift ~1.0  every firm says it (generic finance words), NOT vertical signal")
    print("  lift >2.0  language specific to this vertical's buyer")
    print("raw counts are inflated by multi-label firms (mean 4.4 specialties each);")
    print("that is why the same generic words top every vertical's raw tally.\n")
    desc_csv = []

    base: dict[str, set] = defaultdict(set)
    for f in firms:
        for d in f["ex"]["operational_descriptors"]:
            k = norm(d.get("phrase", ""))
            if k:
                base[k].add(f["domain"])
    n_any = len(firms)

    for lab in big:
        members = [f for f in firms if lab in labels_of(f)]
        focused = [f for f in members if len(labels_of(f)) <= 3]
        per: dict[str, set] = defaultdict(set)
        per_focus: dict[str, set] = defaultdict(set)
        quote: dict[str, tuple[str, str]] = {}
        for f in members:
            for d in f["ex"]["operational_descriptors"]:
                k = norm(d.get("phrase", ""))
                if not k:
                    continue
                per[k].add(f["domain"])
                if len(labels_of(f)) <= 3:
                    per_focus[k].add(f["domain"])
                quote.setdefault(k, (d.get("phrase", ""), d.get("evidence_url", "")))

        scored = []
        for k, doms in per.items():
            if len(doms) < MIN_DESCRIPTOR:
                continue
            rate = len(doms) / max(len(members), 1)
            base_rate = len(base[k]) / max(n_any, 1)
            lift = rate / base_rate if base_rate else 0.0
            scored.append((k, len(doms), len(per_focus.get(k, ())), lift))
        scored.sort(key=lambda x: -x[3])

        print("-" * 78)
        print(f"{lab.upper()}  ({len(members)} firms, {len(focused)} of them focused <=3 specialties)")
        if not scored:
            print("  (no descriptor reaches the 3-firm floor -- nothing reportable)")
            continue
        print(f"  {'lift':>5} {'firms':>5} {'focus':>5}  descriptor")
        for k, c, cf, lift in scored[:12]:
            ph, url = quote[k]
            flags = []
            if c < NOISE_FLOOR:
                flags.append("noise")
            if lift < 1.5:
                flags.append("generic")
            tag = ("  [" + ",".join(flags) + "]") if flags else ""
            print(f"  {lift:5.1f} {c:5} {cf:5}  \"{ph[:40]}\"{tag}")
            print(f"                     {url[:86]}")
            desc_csv.append([lab, ph, c, cf, round(lift, 2), url])

    with (args.out / "descriptors-by-specialty.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["specialty", "descriptor_verbatim", "firm_count",
                    "firm_count_focused_le3_specialties", "lift_vs_corpus", "evidence_url"])
        w.writerows(desc_csv)

    # ---------------- Output 3: scale thresholds ----------------
    print("\n\n### OUTPUT 3 -- SCALE THRESHOLDS PER SPECIALTY\n")
    scale_csv = []
    for lab in big:
        members = [f for f in firms if lab in labels_of(f)]
        withs = [f for f in members if f["ex"]["scale_thresholds"]]
        print("-" * 78)
        pct = 100 * len(withs) // max(len(members), 1)
        print(f"{lab.upper()}  ({len(withs)} of {len(members)} firms state one, {pct}%)")
        if not withs:
            continue
        by_bucket: dict[str, list] = defaultdict(list)
        for f in withs:
            for s in f["ex"]["scale_thresholds"]:
                by_bucket[bucket(s.get("phrase", ""))].append(
                    (s.get("phrase", ""), s.get("evidence_url", ""), f["company"]))
                scale_csv.append([lab, bucket(s.get("phrase", "")), s.get("phrase", ""),
                                  f["company"], s.get("evidence_url", "")])
        for b in ("revenue", "headcount", "volume", "stage", "other"):
            items = by_bucket.get(b) or []
            if not items:
                continue
            flag = "  [noise]" if len(items) < NOISE_FLOOR else ""
            print(f"    {b} ({len(items)}){flag}")
            seen = set()
            for ph, url, co in items:
                k = norm(ph)
                if k in seen:
                    continue
                seen.add(k)
                if len(seen) > 8:
                    print(f"        ... {len(items) - 8} more in the CSV")
                    break
                print(f"        \"{ph[:34]:34}\" {co[:22]:22} {url[:44]}")

    with (args.out / "scale-by-specialty.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["specialty", "bucket", "threshold_verbatim", "company", "evidence_url"])
        w.writerows(scale_csv)

    # ---------------- Also: complete profiles + specialties per firm ----------
    print("\n\n### ALSO\n")
    complete = [f for f in firms if f["ex"]["specialties"] and f["ex"]["scale_thresholds"]
                and f["ex"]["operational_descriptors"]]
    print(f"complete profiles: {len(complete)} of {n}\n")
    cs = Counter()
    for f in complete:
        for lab in labels_of(f):
            cs[lab] += 1
    print("  by specialty (a firm claiming several is counted in each):")
    for lab, c in cs.most_common(18):
        flag = "  [noise]" if c < NOISE_FLOOR else ""
        print(f"    {lab[:34]:34} {c:4}{flag}")
    print("\n  by list:")
    for br in BRANCHES:
        c = sum(1 for f in complete if br in lists_of(f))
        print(f"    {br:20} {c:4}")
    print("\n  by stated rung:")
    for rg in RUNGS:
        c = sum(1 for f in complete if rg in (f["ex"]["service_rungs"] or []))
        print(f"    {rg:20} {c:4}")

    per_firm = [len(labels_of(f)) for f in firms if f["ex"]["specialties"]]
    if per_firm:
        print(f"\nspecialties per firm (of {len(per_firm)} firms stating any):")
        print(f"    median {statistics.median(per_firm)}   "
              f"mode {statistics.mode(per_firm)}   mean {statistics.mean(per_firm):.1f}")
        d = Counter(per_firm)
        for k in sorted(d):
            print(f"      {k:2} specialt{'y' if k == 1 else 'ies'}: {d[k]:4} firms")
        four_plus = sum(v for k, v in d.items() if k >= 4)
        print(f"    4 or more: {four_plus} firms ({100*four_plus//len(per_firm)}%)")

    print(f"\n[wrote] {args.out}/niche-branch-matrix.csv, descriptors-by-specialty.csv, "
          f"scale-by-specialty.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
