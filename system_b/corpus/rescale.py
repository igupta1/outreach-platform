"""Pass 2b -- re-extract scale thresholds, targeting ONLY the client size band.

Pass 2 asked for "any size or volume qualifier stated verbatim" and got exactly
that, which turned out to be the wrong question. Of 787 phrases it returned:

    34%  a real client-size filter      "$2M to $50M+ in revenue", "10k+ SKUs"
     3%  a case-study RESULT            "$1.7M Loss -> $900K Profit"
     4%  the firm's OWN PRICING         "$1,500 / mo"
     6%  CREDENTIALS                    "15 years", "150+ Businesses Served"
     53% ambiguous

All are verbatim and all are size-shaped, so no amount of downstream regex
separates "we serve $2M-$50M companies" from "we saved a client $2M". The
distinction is semantic and has to be asked for.

So this pass re-asks, narrowly: which band does this firm say its CLIENTS fall
into. It writes to a SEPARATE column (`scale_v2`) rather than overwriting
`extraction` -- the first pass is evidence of what the broad question returns
and is worth keeping. Same honesty rule: model proposes, code verifies the
phrase verbatim against a fetched page, unverified is dropped and counted.

Only firms that stated something in pass 1 are re-asked (~390), so this costs
roughly a quarter of a full pass.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from system_b.corpus import store
from system_b.corpus.extract import (MODEL, _call, _pages_for, _Throttle, verify)

_SYSTEM = (
    "You read a professional-services firm's website and record ONLY the size "
    "band of the CLIENTS IT SERVES -- the filter a prospect would use to decide "
    "'am I the right size for this firm'.\n\n"
    "Return JSON: {\"client_size\": [{\"phrase\": ..., \"bucket\": ..., "
    "\"basis\": ...}]}\n"
    "  phrase  their EXACT words, copied character-for-character.\n"
    "  bucket  one of 'revenue', 'headcount', 'volume', 'stage'.\n"
    "            revenue  = money the client makes  ($2M-$50M in revenue, $10M ARR)\n"
    "            headcount= people the client has   (5-50 employees, 10-100 people)\n"
    "            volume   = units the client moves  (10k+ SKUs, 200 transactions/mo,\n"
    "                       50+ entities, 3 locations, 40 providers, 500 doors)\n"
    "            stage    = funding stage           (Series A, pre-seed, pre-IPO)\n"
    "  basis   short verbatim context proving it describes clients, not the firm.\n\n"
    "EXCLUDE, these are NOT client size bands:\n"
    "  * case-study results          '$1.7M Loss to $900K Profit', 'grew 40%',\n"
    "                                 '$150M+ Capital Raised', '$1B+ Value Created'\n"
    "  * the FIRM'S OWN pricing      '$1,500 / mo', 'packages from $500'\n"
    "  * the FIRM'S OWN credentials  '15 years experience', '150+ Businesses\n"
    "                                 Served', 'team of 50 professionals'\n"
    "  * the FIRM'S OWN size or any number describing the firm itself\n"
    "  * dollar figures inside tax/compliance prose ('$600 in income',\n"
    "    'the $18,000 threshold') -- those are rules, not client filters\n\n"
    "MUST BE MEASURABLE. The phrase has to carry an actual NUMBER (a dollar "
    "figure, a count, a range) or a NAMED FUNDING STAGE (pre-seed, Series A, "
    "pre-IPO). Vague size words are NOT thresholds and must be excluded: "
    "'small businesses', 'growing businesses', 'mom-and-pop', 'mid-sized "
    "companies', 'established enterprise', 'SMBs'. A prospect cannot tell "
    "whether they qualify from those, which is the whole point of a threshold.\n\n"
    "A phrase qualifies ONLY if the page uses it to describe who the firm's "
    "clients are or who it works with. If the site states no measurable client "
    "size band, return an empty list -- that is the common and correct answer. "
    "Keep the phrase TIGHT: the qualifier and just enough words to show it "
    "describes clients. Copy it EXACTLY or omit it; a downstream check rejects "
    "anything not found word-for-word."
)

_BUCKETS = ("revenue", "headcount", "volume", "stage")

# The model decides the SEMANTIC question (is this a client size band?), which
# needs judgement. Bucketing is mechanical pattern-matching, and the sample run
# showed the model is bad at it -- it filed "50+ Businesses & Nonprofits" as
# headcount and "small to mid-sized businesses" as stage. So code buckets.
_STAGE_RE = re.compile(r"\b(pre[\s-]?seed|seed[\s-]?(stage|round)?|series\s?[a-e]\b|"
                       r"pre[\s-]?ipo|bootstrapped|venture[\s-]backed)\b", re.I)
_HEAD_RE = re.compile(r"\b\d[\d,]*\s*(?:-|–|to|\+)?\s*\d*\s*\+?\s*"
                      r"(employee|person|people|staff|headcount|fte|seat)", re.I)
_VOL_RE = re.compile(r"\b\d[\d,.]*\s*(?:k|m|mm)?\s*\+?\s*(?:-|–|to)?\s*[\d,.]*\s*(?:k|m)?\s*\+?\s*"
                     r"(sku|unit|order|transaction|propert|door|location|entit|"
                     r"provider|clinic|bed|truck|store|site|grant|job|account)", re.I)
_REV_RE = re.compile(r"\$\s?[\d.,]+\s*(k|m|mm|b|million|billion)?|"
                     r"\b\d[\d,.]*\s*(million|billion)\b|\barr\b|\bebitda\b|"
                     r"\brun[\s-]?rate\b|\bfigure\b", re.I)
_HAS_NUM = re.compile(r"\d")


def bucket_of(phrase: str) -> str:
    """revenue | headcount | volume | stage | other -- in that precedence.
    Stage first: '$4M Series Seed' is a stage claim that happens to name money.
    Headcount and volume before revenue: '650 employees' and '10k+ SKUs' carry
    no '$' but '$120M budgets' does, so money is the last resort."""
    p = phrase or ""
    if _STAGE_RE.search(p):
        return "stage"
    if _HEAD_RE.search(p):
        return "headcount"
    if _VOL_RE.search(p):
        return "volume"
    if _REV_RE.search(p):
        return "revenue"
    return "other"


# A rate is the firm's price, not the client's size. The sample run leaked
# "$40K-$80K/month for 3 to 5 employees" and "$5k - $25k /mo" through the
# model's own exclusion, so code catches it too.
_RATE_RE = re.compile(r"(/|\bper\s+)\s*(mo\b|month|hour|hr\b|week|wk\b|project|"
                      r"seat|yr\b|year)", re.I)
_HAS_ALPHA = re.compile(r"[a-z]{3}", re.I)


def is_measurable(phrase: str) -> bool:
    """A threshold a prospect can test themselves against. 'growing businesses'
    is not one; '$2M-$50M in revenue' is.

    Three gates, all mechanical:
      * carries a number or a named stage
      * is not a per-period RATE (that is the firm's pricing)
      * carries real words -- a bare "3 - 5" names no unit and means nothing
    """
    p = phrase or ""
    if _RATE_RE.search(p):
        return False
    if not _HAS_ALPHA.search(p):
        return False
    return bool(_HAS_NUM.search(p) or _STAGE_RE.search(p))


def rescale_one(client: Any, firm: dict, throttle: _Throttle) -> dict[str, Any]:
    pages = _pages_for(firm["domain"])
    out: dict[str, Any] = {"client_size": [], "dropped_unverified": 0, "error": ""}
    if not pages:
        out["error"] = "no cached pages"
        return out
    try:
        raw = _call_scale(client, pages, firm.get("company") or firm["domain"], throttle)
    except Exception as exc:               # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        return out
    kept, dropped = verify(raw.get("client_size") or [], pages)
    # Two code-side gates after the verbatim check: drop anything without an
    # actual number or named stage, and overwrite the model's bucket with one
    # derived from the phrase itself.
    final, vague = [], 0
    for k in kept:
        if not is_measurable(k.get("phrase", "")):
            vague += 1
            continue
        k["model_bucket"] = k.get("bucket")
        k["bucket"] = bucket_of(k["phrase"])
        final.append(k)
    out["client_size"] = final
    out["dropped_unverified"] = dropped
    out["dropped_vague"] = vague
    return out


def _call_scale(client: Any, pages: dict[str, str], company: str,
                throttle: _Throttle) -> dict:
    """Same transport as extract._call, different system prompt."""
    import json as _json
    import random
    import time
    body = "\n\n".join(f"URL: {u}\n{t}" for u, t in pages.items())
    for attempt in range(5):
        throttle.wait()
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": f"Firm: {company}\n\n{body}"}])
            return _json.loads(resp.choices[0].message.content or "{}")
        except Exception as exc:            # noqa: BLE001
            name = type(exc).__name__
            if "RateLimit" in name or "APIStatus" in name or "APIConnection" in name:
                time.sleep(min(2 ** attempt + random.random(), 30))
                continue
            raise
    raise RuntimeError("RateLimitError: exhausted retries")


def ensure_column(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(firms)")}
    if "scale_v2" not in cols:
        conn.execute("ALTER TABLE firms ADD COLUMN scale_v2 TEXT")
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from openai import OpenAI

    from system_b import config

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--rpm", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", action="store_true", help="re-ask firms already done")
    a = ap.parse_args(argv)

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY, max_retries=0)
    throttle = _Throttle(a.rpm)
    conn = store.connect()
    ensure_column(conn)

    todo = []
    for r in conn.execute("SELECT * FROM firms WHERE extraction IS NOT NULL"):
        d = dict(r)
        if d.get("scale_v2") and not a.redo:
            continue
        try:
            ex = json.loads(d["extraction"])
        except (TypeError, json.JSONDecodeError):
            continue
        if ex.get("error") or not ex.get("scale_thresholds"):
            continue          # only re-ask firms that stated SOMETHING in pass 1
        todo.append(d)
    if a.limit:
        todo = todo[: a.limit]

    print(f"[rescale] {len(todo)} firm(s), {a.workers} workers, {a.rpm} rpm")
    done = errs = kept = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for firm, res in zip(todo, pool.map(lambda f: rescale_one(client, f, throttle), todo)):
            conn.execute("UPDATE firms SET scale_v2=? WHERE domain=?",
                         (json.dumps(res), firm["domain"]))
            conn.commit()
            done += 1
            errs += 1 if res.get("error") else 0
            kept += len(res.get("client_size") or [])
            if done % 50 == 0:
                print(f"[rescale] {done}/{len(todo)}  ({errs} errors, {kept} kept)", flush=True)
    print(f"[rescale] {done} done, {errs} errors, {kept} client-size phrases kept")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
