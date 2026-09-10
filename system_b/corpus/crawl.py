"""Pass 1 -- fetch every firm twice and record what each method could read.

Two fetches per firm, deliberately:

  * the REGEX path (`research.fetcher`, no JavaScript) -- what the pipeline
    reads today
  * the RENDERED path (headless chromium) -- what a person reads

Recording both is the whole point of this pass. It separates three things the
80%-generalist number currently merges:

    fetch failure   the domain is dead, blocked, or timed out
    unreadable      the site renders fine but the no-JS fetcher sees a shell
    genuinely thin  the rendered page really does say almost nothing

Only the second is a bug. No LLM is called here, so this pass costs nothing but
time and answers whether pass 2 is worth running.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from system_b.corpus import store
from system_b.research.fetcher import _UA, html_to_text

# Pages that carry a stated vertical. Extends the pipeline's own list with the
# words firms actually title these pages with.
PAGE_KEYWORDS = (
    "about", "industr", "who-we-serve", "whoweserve", "who_we_serve", "client",
    "case-stud", "casestud", "work", "portfolio", "sector", "vertical",
    "expertise", "practice", "services", "markets", "specialt", "niche",
    "solutions", "our-focus",
)
MAX_PAGES = 6                    # homepage + 5; beyond this the yield collapses
NAV_TIMEOUT_MS = 20_000
IDLE_TIMEOUT_MS = 5_000
_BLOCKED_RESOURCES = ("image", "media", "font", "stylesheet")


def normalize(url: str | None) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u.rstrip("/")


def load_firms(paths: list[Path]) -> list[dict[str, Any]]:
    """Dedupe on EMAIL across the lists, then collapse to one row per DOMAIN.

    Both steps matter and they answer different questions. Email dedupe is what
    stops the same person being counted three times; domain collapse is what
    stops the same site being crawled three times. `source_lists` survives both,
    because how often one firm appears on the cfo, accounting AND bookkeeping
    lists is itself a finding about whether the three-campaign split is real."""
    from system_b.prospects import read_apollo_csv

    by_email: dict[str, dict] = {}
    for p in paths:
        for row in read_apollo_csv(p):
            email = (row.get("email") or "").strip().lower()
            if not email:
                continue
            rec = by_email.setdefault(email, {**row, "source_lists": set()})
            rec["source_lists"].add(p.stem)

    by_domain: dict[str, dict] = {}
    for email, row in by_email.items():
        dom = store.domain_of(row.get("website"))
        if not dom:
            continue
        f = by_domain.setdefault(dom, {"domain": dom, "website": normalize(row["website"]),
                                       "company": row.get("firm_name"),
                                       "source_lists": set(), "emails": set()})
        f["source_lists"] |= row["source_lists"]
        f["emails"].add(email)
    return list(by_domain.values())


def fetch_regex(url: str) -> tuple[dict[str, str], str]:
    """The no-JS path, exactly as the pipeline does it today. Returns raw HTML
    per page -- extraction reads the cached HTML, never the stripped text, so
    changing how text is derived never means re-crawling."""
    pages: dict[str, str] = {}
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers={"User-Agent": _UA}) as c:
            r = c.get(url)
            r.raise_for_status()
            pages[url] = r.text
            for sub in _discover(r.text, url)[: MAX_PAGES - 1]:
                try:
                    rr = c.get(sub)
                    if rr.status_code == 200:
                        pages[sub] = rr.text
                except Exception:      # noqa: BLE001
                    pass
        return pages, ""
    except Exception as exc:           # noqa: BLE001
        return pages, type(exc).__name__


def _discover(html: str, base: str) -> list[str]:
    host = urlparse(base).netloc.replace("www.", "")
    out: list[str] = []
    for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I)[:600]:
        hay = f"{href.lower()} {re.sub(r'<[^>]+>', ' ', label).lower()}"
        if not any(k in hay for k in PAGE_KEYWORDS):
            continue
        u = urljoin(base, href.split("#")[0]).rstrip("/")
        if urlparse(u).netloc.replace("www.", "") != host or u == base or u in out:
            continue
        out.append(u)
    return out


async def _render_firm(context: Any, firm: dict) -> dict[str, Any]:
    """Render the homepage, discover from the RENDERED DOM, render the rest."""
    base = firm["website"]
    pages: dict[str, str] = {}
    tried = 0
    err = ""

    async def one(url: str) -> str:
        nonlocal tried
        tried += 1
        page = await context.new_page()
        try:
            await page.route("**/*", lambda route: asyncio.ensure_future(
                route.abort() if route.request.resource_type in _BLOCKED_RESOURCES
                else route.continue_()))
            await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
            except Exception:          # noqa: BLE001
                pass                   # settled enough
            return await page.content()
        except Exception as exc:       # noqa: BLE001
            raise RuntimeError(type(exc).__name__) from exc
        finally:
            await page.close()

    try:
        home = await one(base)
        pages[base] = home
    except RuntimeError as exc:
        return {"pages": {}, "tried": tried, "error": str(exc)}

    # Discovery runs on the RENDERED dom -- a nav rendered by JavaScript is
    # invisible to the regex path, which is part of why it finds so little.
    for sub in _discover(home, base)[: MAX_PAGES - 1]:
        try:
            pages[sub] = await one(sub)
        except RuntimeError:
            pass
    return {"pages": pages, "tried": tried, "error": err}


# Below this the no-JS fetch has not read a usable page, so a render is worth
# its 2s. Deliberately above THIN_MIN_CHARS: a site sitting just over the
# classifier's floor is still one where rendering may find the page that
# actually states the vertical (graphadvisors clears 350 on one server-rendered
# page while its homepage returns 56 chars).
RENDER_IF_UNDER = 1_500


async def crawl(firms: list[dict], *, concurrency: int, progress_every: int = 25) -> None:
    from playwright.async_api import async_playwright

    conn = store.connect()
    done = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        sem = asyncio.Semaphore(concurrency)

        async def work(firm: dict) -> None:
            """Cheap path first. Measured on a random 150-firm sample, 86% of
            these sites return a median 14,834 readable characters with no
            JavaScript at all, and of 12 firms rendered outright, 11 gained
            nothing. Rendering everything would spend an hour to fix 14%."""
            nonlocal done
            async with sem:
                regex_pages, regex_err = await asyncio.to_thread(fetch_regex, firm["website"])
                regex_chars = sum(len(html_to_text(h)) for h in regex_pages.values())
                pages, rendered_chars, err = regex_pages, 0, regex_err

                if regex_chars < RENDER_IF_UNDER:
                    ctx = await browser.new_context(
                        user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/120.0.0.0 Safari/537.36"),
                        viewport={"width": 1280, "height": 900})
                    try:
                        res = await _render_firm(ctx, firm)
                    finally:
                        await ctx.close()
                    rendered_chars = sum(len(html_to_text(h)) for h in res["pages"].values())
                    if rendered_chars > regex_chars:
                        pages, err = res["pages"], res["error"]
                else:
                    rendered_chars = regex_chars     # not rendered; they agree by definition

                for u, h in pages.items():
                    store.write_page(firm["domain"], u, h)
                store.save_crawl(
                    conn, firm["domain"],
                    pages_tried=max(len(pages), 1), pages_ok=len(pages),
                    chars_regex=regex_chars, chars_rendered=max(rendered_chars, regex_chars),
                    fetch_error="" if pages else (err or regex_err or "empty"))
                done += 1
                if done % progress_every == 0:
                    print(f"[crawl] {done}/{len(firms)}", flush=True)

        await asyncio.gather(*(work(f) for f in firms))
    print(f"[crawl] {done}/{len(firms)} complete", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="sources", nargs="+", required=True, type=Path)
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    firms = load_firms(a.sources)
    conn = store.connect()
    added = store.seed(conn, firms)
    todo = store.pending(conn, "crawl")
    if a.limit:
        todo = todo[: a.limit]
    print(f"[crawl] {len(firms)} unique firms ({added} new); {len(todo)} to crawl")
    if not todo:
        return 0
    asyncio.run(crawl([dict(r) for r in todo], concurrency=a.concurrency))
    return 0


if __name__ == "__main__":
    sys.exit(main())
