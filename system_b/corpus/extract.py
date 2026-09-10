"""Pass 2 -- extract what each firm SAYS it does, from the cached HTML.

Open-vocabulary on purpose. The pipeline's Gate A maps a stated phrase onto a
fixed taxonomy and returns None for anything uncurated, which is correct when
the output is a rendered email -- copy must never print a raw token. It is
exactly wrong when the output is an ANALYSIS. Measured on the first pass, 156
firms stated a specialty that was discarded for having no label:

    "ESOP companies"        "Biotech & Life Science Companies"
    "VC Funds"              "Public & Pre-Public Companies"
    "fine beverage makers and purveyors"

Several are sharper than anything in the taxonomy. Forcing them into
NICHE_DISPLAY, or dropping them, destroys the signal this pass exists to count.
So the model records the firm's own words and code verifies them; the mapping
question comes later, once we know what is actually out there.

## The honesty rule is unchanged

The model PROPOSES; code VERIFIES. Every extracted string must appear verbatim
on a page we actually fetched -- same discipline as `research/classifier.py`,
same tolerance (case and whitespace only). Anything unverified is dropped and
counted, so hallucination shows up as a number rather than as data.

## Rate limiting

The previous run went 16-way concurrent and OpenAI rate-limited 699 of 1,557
firms -- 45% of the corpus silently never classified, which made the headline
"80% generalist" meaningless. This pass caps concurrency, retries 429s with
backoff, and records a per-firm error rather than letting a throttle masquerade
as a finding.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from system_b.corpus import store
from system_b.research.fetcher import html_to_text

MODEL = "gpt-4o-mini"
MAX_CHARS_PER_PAGE = 6_000
MAX_PAGES = 6

_SYSTEM = (
    "You read a professional-services firm's own website and record what it says "
    "about the clients it serves. You are cataloguing claims, not judging them, "
    "and you never infer: if the site does not say it, it does not exist.\n\n"
    "Return JSON with these keys:\n"
    "specialties: list of {phrase, kind, strength}. `phrase` is their EXACT words, "
    "copied character-for-character from the page. `kind` is 'industry' (dental, "
    "construction, nonprofits, SaaS), 'stage' (early-stage startups, pre-IPO, "
    "Series A), or 'structure' (ESOP companies, VC funds, franchises, "
    "multi-entity). `strength` is 'dedicated' when the claim has its own page, "
    "hero heading, or section devoted to it; 'listed' when it is one entry in a "
    "grid or list of several; 'mentioned' when it appears in passing prose.\n"
    "scale_thresholds: list of {phrase} -- any size or volume qualifier stated "
    "verbatim: '10k+ SKUs', '$1M-$10M in revenue', '5-50 employees', "
    "'Series A and B', 'multi-location', '$50M AUM'. Empty if none.\n"
    "operational_descriptors: list of {phrase} -- the specific finance problems "
    "they name: 'landed cost', 'multi-channel reconciliation', 'job costing', "
    "'grant accounting', 'trust accounting', 'revenue cycle', 'capital calls', "
    "'WIP reporting', 'inventory accounting'. These are the sharpest signal of "
    "who their buyer is. Empty if none.\n"
    "service_rungs: subset of ['bookkeeping','accounting','cfo'] -- which rungs "
    "this firm says it sells. Many sell all three.\n\n"
    "Copy every phrase EXACTLY as written or omit it. A downstream check rejects "
    "anything not found word-for-word on the page, so an approximation is worse "
    "than nothing. Return empty lists rather than guessing."
)

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").lower()).strip()


class _Throttle:
    """Token-bucket over the whole process. The previous run had no ceiling and
    lost 45% of the corpus to 429s."""

    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / max(per_minute, 1)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
                now = time.monotonic()
            self._next = now + self._interval


def _pages_for(domain: str) -> dict[str, str]:
    """Cached HTML -> visible text, longest pages first (the ones that say the
    most), capped so one enormous page cannot crowd out the rest."""
    pages = {u: html_to_text(h) for u, h in store.read_pages(domain).items()}
    pages = {u: t for u, t in pages.items() if t.strip()}
    ranked = sorted(pages.items(), key=lambda kv: -len(kv[1]))[:MAX_PAGES]
    return {u: t[:MAX_CHARS_PER_PAGE] for u, t in ranked}


def _call(client: Any, pages: dict[str, str], company: str, throttle: _Throttle) -> dict:
    body = "\n\n".join(f"URL: {u}\n{t}" for u, t in pages.items())
    for attempt in range(5):
        throttle.wait()
        try:
            resp = client.chat.completions.create(
                model=MODEL, temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": f"Firm: {company}\n\n{body}"}])
            return json.loads(resp.choices[0].message.content or "{}")
        except Exception as exc:            # noqa: BLE001
            name = type(exc).__name__
            if "RateLimit" in name or "APIStatus" in name or "APIConnection" in name:
                time.sleep(min(2 ** attempt + random.random(), 30))
                continue
            raise
    raise RuntimeError("RateLimitError: exhausted retries")


def verify(items: list[dict], pages: dict[str, str], key: str = "phrase") -> tuple[list[dict], int]:
    """Keep only claims whose phrase appears VERBATIM on a fetched page, and
    attach the URL it was found on. Returns (kept, dropped)."""
    kept, dropped = [], 0
    haystacks = {u: _norm(t) for u, t in pages.items()}
    for item in items or []:
        phrase = (item or {}).get(key) if isinstance(item, dict) else item
        phrase = str(phrase or "").strip()
        if not phrase:
            dropped += 1
            continue
        needle = _norm(phrase)
        found = next((u for u, h in haystacks.items() if needle and needle in h), None)
        if found is None:
            dropped += 1
            continue
        row = dict(item) if isinstance(item, dict) else {key: phrase}
        row[key] = phrase
        row["evidence_url"] = found
        kept.append(row)
    return kept, dropped


def extract_one(client: Any, firm: dict, throttle: _Throttle) -> dict[str, Any]:
    pages = _pages_for(firm["domain"])
    out: dict[str, Any] = {"specialties": [], "scale_thresholds": [],
                           "operational_descriptors": [], "service_rungs": [],
                           "dropped_unverified": 0, "pages_read": len(pages), "error": ""}
    if not pages:
        out["error"] = "no cached pages"
        return out
    try:
        raw = _call(client, pages, firm.get("company") or firm["domain"], throttle)
    except Exception as exc:               # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        return out
    dropped = 0
    for field in ("specialties", "scale_thresholds", "operational_descriptors"):
        kept, d = verify(raw.get(field) or [], pages)
        out[field] = kept
        dropped += d
    rungs = raw.get("service_rungs") or []
    out["service_rungs"] = [r for r in rungs if r in ("bookkeeping", "accounting", "cfo")]
    out["dropped_unverified"] = dropped
    return out


def main(argv: list[str] | None = None) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from openai import OpenAI

    from system_b import config

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--rpm", type=int, default=180, help="request ceiling per minute")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    config.require("OPENAI_API_KEY")
    client = OpenAI(api_key=config.OPENAI_API_KEY, max_retries=0)
    throttle = _Throttle(a.rpm)
    conn = store.connect()
    todo = [dict(r) for r in store.pending(conn, "extract")]
    if a.limit:
        todo = todo[: a.limit]
    print(f"[extract] {len(todo)} firm(s) to extract, {a.workers} workers, {a.rpm} rpm ceiling")
    done = errs = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for firm, res in zip(todo, pool.map(lambda f: extract_one(client, f, throttle), todo)):
            store.save_extraction(conn, firm["domain"], res)
            done += 1
            errs += 1 if res.get("error") else 0
            if done % 50 == 0:
                print(f"[extract] {done}/{len(todo)}  ({errs} errors)", flush=True)
    print(f"[extract] {done} done, {errs} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
