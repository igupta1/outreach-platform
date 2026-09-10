"""The focused corpus: firms claiming <=3 specialties, plus the corrected scale.

Two corrections to the headline numbers, both of which shrink them:

  * The mean firm claims 4.4 specialties and 48% claim four or more. For those,
    "specialty" is a services-grid checklist, not a focus, and counting them
    inflates every vertical. FOCUS_MAX keeps firms whose claim plausibly means
    something.
  * A "scale threshold" from pass 2 was any size-shaped phrase, which swept in
    case-study results, the firm's own pricing, and credentials. `rescale.py`
    re-asked the narrow question; this module reads `scale_v2` and ignores the
    old column entirely.

A "distinctive" operational descriptor is one with LIFT >= MIN_LIFT against the
whole corpus -- language that separates this vertical from the others. Generic
finance vocabulary ("cash flow", "budgeting") sits at lift ~1.0 and is excluded,
because a descriptor every firm uses cannot tell you who a buyer is.

Lift is computed on the FULL corpus, not the focused subset: the question "is
this word distinctive" is about the language overall, and the focused subset is
too small per vertical to estimate a rate from.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from system_b.corpus import store
from system_b.corpus.analyze import canon, load

FOCUS_MAX = 3        # a firm claiming more than this is a checklist, not a focus
MIN_FIRMS = 20       # report a specialty only at this many FOCUSED firms
MIN_LIFT = 2.0       # a descriptor below this is generic finance vocabulary
MIN_DESC_FIRMS = 3   # a descriptor seen in fewer firms than this is not evidence


def labels_of(f) -> set[str]:
    return {canon(s.get("phrase", "")) for s in f["ex"]["specialties"]}


def strong(f, label: str) -> bool:
    return any(canon(s.get("phrase", "")) == label
               and s.get("strength") in ("dedicated", "listed")
               for s in f["ex"]["specialties"])


def scale_of(f) -> list[dict]:
    """Corrected client-size bands only. Absent scale_v2 means the firm stated
    nothing in pass 1 and was never re-asked, which is a real zero."""
    try:
        return (json.loads(f["scale_v2"] or "{}") or {}).get("client_size") or []
    except (TypeError, json.JSONDecodeError):
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("system_b/data/corpus"))
    a = ap.parse_args(argv)

    conn = store.connect()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(firms)")}
    firms = load(conn)
    if "scale_v2" not in cols:
        print("scale_v2 column missing -- run `python -m system_b.corpus.rescale` first")
        return 1
    a.out.mkdir(parents=True, exist_ok=True)

    # --- descriptor lift, computed on the FULL corpus -------------------
    base: dict[str, set] = defaultdict(set)
    for f in firms:
        for d in f["ex"]["operational_descriptors"]:
            k = (d.get("phrase") or "").strip().lower()
            if k:
                base[k].add(f["domain"])
    n_all = len(firms)

    full_counts = Counter()
    for f in firms:
        for lab in labels_of(f):
            full_counts[lab] += 1

    distinctive: dict[str, set[str]] = {}
    for lab, tot in full_counts.items():
        members = [f for f in firms if lab in labels_of(f)]
        per: dict[str, set] = defaultdict(set)
        for f in members:
            for d in f["ex"]["operational_descriptors"]:
                k = (d.get("phrase") or "").strip().lower()
                if k:
                    per[k].add(f["domain"])
        keep = set()
        for k, doms in per.items():
            if len(doms) < MIN_DESC_FIRMS:
                continue
            rate = len(doms) / max(len(members), 1)
            br = len(base[k]) / max(n_all, 1)
            if br and rate / br >= MIN_LIFT:
                keep.add(k)
        distinctive[lab] = keep

    def has_distinctive(f, lab: str) -> bool:
        keep = distinctive.get(lab) or set()
        return any((d.get("phrase") or "").strip().lower() in keep
                   for d in f["ex"]["operational_descriptors"])

    # --- the focused subset ---------------------------------------------
    focused = [f for f in firms if f["ex"]["specialties"] and len(labels_of(f)) <= FOCUS_MAX]
    print(f"\n{'='*78}")
    print(f"FOCUSED CORPUS: {len(focused)} firms claiming <= {FOCUS_MAX} specialties "
          f"(of {len(firms)} extracted, {len([f for f in firms if f['ex']['specialties']])} "
          f"stating any)")
    print("scale = corrected client-size band (rescale.py); descriptor = lift >= 2.0")
    print("=" * 78)

    fc = Counter()
    for f in focused:
        for lab in labels_of(f):
            fc[lab] += 1
    big = [lab for lab, c in fc.most_common() if c >= MIN_FIRMS]

    print(f"\n{'specialty':26} {'firms':>5} {'strong':>7} {'scale':>6} {'distinct':>9} "
          f"{'complete':>9}")
    rows = []
    for lab in big:
        mem = [f for f in focused if lab in labels_of(f)]
        s = sum(1 for f in mem if strong(f, lab))
        sc = sum(1 for f in mem if scale_of(f))
        ds = sum(1 for f in mem if has_distinctive(f, lab))
        cp = sum(1 for f in mem if strong(f, lab) and scale_of(f) and has_distinctive(f, lab))
        print(f"{lab[:26]:26} {len(mem):5} {s:7} {sc:6} {ds:9} {cp:9}")
        rows.append([lab, len(mem), s, sc, ds, cp,
                     "; ".join(sorted(distinctive.get(lab) or ())[:10])])

    with (a.out / "focused-specialty-matrix.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["specialty", "focused_firms", "strong_signal", "with_client_scale",
                    "with_distinctive_descriptor", "complete_all_three",
                    "distinctive_descriptors"])
        w.writerows(rows)

    # --- the focused complete-profile list ------------------------------
    print(f"\n\n{'='*78}\nFOCUSED COMPLETE PROFILES")
    print("strong specialty signal + a real client-size band + distinctive descriptor")
    print("=" * 78)
    out_rows = []
    for f in focused:
        labs = [l for l in labels_of(f)
                if strong(f, l) and has_distinctive(f, l)]
        sc = scale_of(f)
        if not labs or not sc:
            continue
        d_hit = sorted({(d.get("phrase") or "") for l in labs
                        for d in f["ex"]["operational_descriptors"]
                        if (d.get("phrase") or "").strip().lower() in (distinctive.get(l) or set())})
        out_rows.append({
            "company": f["company"], "website": f["website"],
            "source_lists": f["source_lists"],
            "specialties": "; ".join(sorted(labs)),
            "scale": "; ".join(f"[{x['bucket']}] {x['phrase']}" for x in sc),
            "descriptors": "; ".join(d_hit),
            "rungs": "; ".join(f["ex"]["service_rungs"] or []),
            "evidence": "; ".join(sorted({x.get("evidence_url", "") for x in sc if x.get("evidence_url")})),
        })

    print(f"\n{len(out_rows)} firms\n")
    for r in sorted(out_rows, key=lambda x: x["specialties"]):
        print(f"  {r['company'][:34]:34} [{r['specialties'][:30]:30}]")
        print(f"      scale: {r['scale'][:78]}")
        print(f"      pain : {r['descriptors'][:78]}")

    by_spec = Counter()
    for r in out_rows:
        for l in r["specialties"].split("; "):
            by_spec[l] += 1
    print("\n  by specialty:")
    for l, c in by_spec.most_common():
        print(f"    {l[:34]:34} {c:4}")
    by_list = Counter()
    for r in out_rows:
        for b in (r["source_lists"] or "").split(","):
            if b:
                by_list[b] += 1
    print("\n  by list:")
    for b, c in by_list.most_common():
        print(f"    {b:20} {c:4}")

    with (a.out / "focused-complete-profiles.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()) if out_rows else
                           ["company", "website", "source_lists", "specialties", "scale",
                            "descriptors", "rungs", "evidence"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n[wrote] {a.out}/focused-specialty-matrix.csv, focused-complete-profiles.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
