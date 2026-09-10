"""Task 3 -- count and rank what the corpus actually claims.

Answers the question the whole exercise exists for: which specialty clusters
appear often enough to be worth building a signal source for. That decision has
been made on guesswork (IRS 990? NPPES? permits?) against a random Apollo
sample; this replaces the guess with a count of what firms publish about
themselves.

The Benzion profile is the shape being counted. His site already carried two of
the three filters he later spelled out over four emails -- "E-commerce &
Inventory" as a dedicated specialty, "moving 10k+ SKUs" as a scale threshold --
so a firm carrying specialty + scale + a named operational problem is one whose
signal could be built with no conversation at all. `complete_profiles` counts
exactly those.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from system_b.corpus import store

_WS = re.compile(r"\s+")
# Cluster near-identical claims: "nonprofits" / "non-profits" / "nonprofit
# organizations" are one specialty, not three.
_CANON = [
    (r"non[\s-]?profit|501\(?c\)?", "nonprofit"),
    (r"\be-?commerce|online (retail|seller|store)|shopify|dtc|d2c", "ecommerce"),
    (r"construction|contractor|builder|trades", "construction"),
    (r"real ?estate|property manage|landlord|rental", "real estate"),
    (r"health ?care|medical|clinic|practice|dental|veterinar", "healthcare"),
    (r"restaurant|hospitality|food service|bar\b|brewery", "restaurant/hospitality"),
    (r"saas|software|tech(nology)? compan|b2b software", "software/saas"),
    (r"manufactur|industrial|fabricat", "manufacturing"),
    (r"law ?firm|legal|attorney|solo practitioner", "legal"),
    (r"startup|early[\s-]stage|pre[\s-]seed|seed[\s-]stage|venture[\s-]backed", "startups (stage)"),
    (r"series [a-d]\b|growth[\s-]stage|scale[\s-]up|pre[\s-]ipo", "growth-stage (stage)"),
    (r"\besop\b", "ESOP"),
    (r"\bvc\b|venture capital|private equity|\bpe\b|fund\b|family office", "funds/PE/VC"),
    (r"agenc(y|ies)|creative|marketing firm", "agencies"),
    (r"cannabis|dispensar", "cannabis"),
    (r"biotech|life science|pharma", "biotech/life science"),
    (r"franchis", "franchise"),
    (r"trucking|logistics|freight|fleet", "logistics"),
    (r"church|ministr|faith", "faith-based"),
    (r"consult(ing|ant)", "consulting"),
    (r"professional service", "professional services"),
    # Any phrasing of "small/growing/founder-led business" names a size or
    # ownership structure, not an industry -- it can't drive a public-data
    # signal source the way "nonprofit" or "healthcare" can, so it belongs in
    # one bucket, not two dozen near-duplicate ones (fold added after a
    # second-opinion review counted ~430 of 1,464 firms scattered across
    # unfolded variants of this same non-answer).
    (r"small business|smb|business owner|entrepreneur|small.{0,4}(to|and|&).{0,4}"
     r"(mid|medium)[\s-]?siz|businesses? of all sizes|growing (business|compan)|"
     r"founder-?led|^founders$|solopreneur|service-?based business|closely held|"
     r"established (business|compan)", "(generic: small business)"),
]


def canon(phrase: str) -> str:
    p = _WS.sub(" ", (phrase or "").lower()).strip()
    for pattern, label in _CANON:
        if re.search(pattern, p):
            return label
    return p[:40]


def load(conn) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM firms WHERE extraction IS NOT NULL"):
        d = dict(r)
        try:
            d["ex"] = json.loads(d["extraction"])
        except (TypeError, json.JSONDecodeError):
            continue
        if d["ex"].get("error"):
            continue
        out.append(d)
    return out


def report(conn, out_dir: Path) -> None:
    firms = load(conn)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(firms)
    print(f"\n{'='*70}\nCORPUS: {n} firms with a verified extraction\n{'='*70}")

    # --- 1. specialty frequency, split by strength ---
    by_strength: dict[str, Counter] = defaultdict(Counter)
    overall = Counter()
    kinds: dict[str, Counter] = defaultdict(Counter)
    for f in firms:
        seen = set()
        for s in f["ex"]["specialties"]:
            lab = canon(s.get("phrase", ""))
            if lab in seen:
                continue
            seen.add(lab)
            overall[lab] += 1
            by_strength[s.get("strength", "?")][lab] += 1
            kinds[lab][s.get("kind", "?")] += 1
    print(f"\n--- 1. SPECIALTY FREQUENCY (top 25 of {len(overall)}) ---")
    print(f"{'specialty':30} {'firms':>6} {'dedicated':>10} {'listed':>7} {'kind':>12}")
    for lab, c in overall.most_common(25):
        k = kinds[lab].most_common(1)[0][0] if kinds[lab] else "?"
        print(f"  {lab[:28]:28} {c:6} {by_strength['dedicated'][lab]:10} "
              f"{by_strength['listed'][lab]:7} {k:>12}")

    # --- 2. specialty x rung ---
    print("\n--- 2. SPECIALTY x SERVICE RUNG ---")
    rung: dict[str, Counter] = defaultdict(Counter)
    for f in firms:
        rs = f["ex"]["service_rungs"] or ["(unstated)"]
        for s in {canon(x.get("phrase", "")) for x in f["ex"]["specialties"]}:
            for r in rs:
                rung[s][r] += 1
    print(f"{'specialty':30} {'bookkeeping':>12} {'accounting':>11} {'cfo':>5}")
    for lab, _ in overall.most_common(14):
        c = rung[lab]
        print(f"  {lab[:28]:28} {c['bookkeeping']:12} {c['accounting']:11} {c['cfo']:5}")

    # --- 3. scale thresholds ---
    print("\n--- 3. SCALE THRESHOLDS (what firms name as their size band) ---")
    with_scale = [f for f in firms if f["ex"]["scale_thresholds"]]
    print(f"  {len(with_scale)} of {n} firms state one ({100*len(with_scale)//max(n,1)}%)")
    for f in with_scale[:25]:
        sp = ", ".join(sorted({canon(x.get('phrase','')) for x in f['ex']['specialties']})) or "-"
        for t in f["ex"]["scale_thresholds"][:2]:
            print(f"    {(f['company'] or f['domain'])[:26]:26} [{sp[:24]:24}] \"{t['phrase'][:44]}\"")

    # --- 4. co-occurrence ---
    print("\n--- 4. SPECIALTIES THAT APPEAR TOGETHER (top 15 pairs) ---")
    pairs = Counter()
    for f in firms:
        labs = sorted({canon(x.get("phrase", "")) for x in f["ex"]["specialties"]})
        for a, b in combinations(labs, 2):
            pairs[(a, b)] += 1
    for (a, b), c in pairs.most_common(15):
        print(f"  {c:4}  {a[:30]} + {b[:30]}")

    # --- 5. operational descriptors per specialty ---
    print("\n--- 5. OPERATIONAL LANGUAGE, by specialty ---")
    ops: dict[str, Counter] = defaultdict(Counter)
    for f in firms:
        labs = {canon(x.get("phrase", "")) for x in f["ex"]["specialties"]} or {"(no specialty)"}
        for d in f["ex"]["operational_descriptors"]:
            for lab in labs:
                ops[lab][_WS.sub(" ", d["phrase"].lower().strip())[:40]] += 1
    for lab, _ in overall.most_common(8):
        top = ", ".join(f'"{p}"' for p, _ in ops[lab].most_common(5))
        if top:
            print(f"  {lab[:26]:26} {top[:110]}")

    # --- 6. complete profiles ---
    print("\n--- 6. COMPLETE PROFILES (specialty + scale + operational problem) ---")
    complete = [f for f in firms
                if f["ex"]["specialties"] and f["ex"]["scale_thresholds"]
                and f["ex"]["operational_descriptors"]]
    print(f"  {len(complete)} of {n} firms ({100*len(complete)//max(n,1)}%) -- buildable with no conversation")
    for f in complete[:20]:
        sp = ", ".join(sorted({canon(x.get('phrase','')) for x in f['ex']['specialties']}))[:34]
        print(f"    {(f['company'] or f['domain'])[:24]:24} [{sp:34}] "
              f"\"{f['ex']['scale_thresholds'][0]['phrase'][:26]}\" + "
              f"\"{f['ex']['operational_descriptors'][0]['phrase'][:26]}\"")

    # --- 7. list overlap ---
    print("\n--- 7. LIST OVERLAP vs STATED RUNGS ---")
    ov = Counter()
    for f in firms:
        ov[len((f["source_lists"] or "").split(","))] += 1
    print(f"  firms on 1 list: {ov[1]}   2 lists: {ov[2]}   3 lists: {ov[3]}")
    multi = [f for f in firms if len((f["source_lists"] or "").split(",")) > 1]
    all3 = [f for f in multi if len(f["ex"]["service_rungs"]) == 3]
    print(f"  of the {len(multi)} on 2+ lists, {len(all3)} state all three rungs on their site")
    rc = Counter(len(f["ex"]["service_rungs"]) for f in firms)
    print(f"  rungs stated per firm: {dict(sorted(rc.items()))}")

    # --- CSV ---
    path = out_dir / "corpus-extraction.csv"
    cols = ["domain", "company", "source_lists", "specialties", "specialty_kinds",
            "specialty_strength", "scale_thresholds", "operational_descriptors",
            "service_rungs", "raw_evidence", "pages_read", "dropped_unverified"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for f in firms:
            ex = f["ex"]
            w.writerow({
                "domain": f["domain"], "company": f["company"] or "",
                "source_lists": f["source_lists"] or "",
                "specialties": " | ".join(s["phrase"] for s in ex["specialties"]),
                "specialty_kinds": " | ".join(s.get("kind", "") for s in ex["specialties"]),
                "specialty_strength": " | ".join(s.get("strength", "") for s in ex["specialties"]),
                "scale_thresholds": " | ".join(s["phrase"] for s in ex["scale_thresholds"]),
                "operational_descriptors": " | ".join(s["phrase"] for s in ex["operational_descriptors"]),
                "service_rungs": ",".join(ex["service_rungs"]),
                "raw_evidence": json.dumps({k: [{"phrase": x["phrase"], "url": x["evidence_url"]}
                                                for x in ex[k]]
                                            for k in ("specialties", "scale_thresholds",
                                                      "operational_descriptors")}),
                "pages_read": ex.get("pages_read", 0),
                "dropped_unverified": ex.get("dropped_unverified", 0)})
    print(f"\n[analyze] per-firm CSV -> {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("system_b/data/corpus"))
    a = ap.parse_args(argv)
    report(store.connect(), a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
