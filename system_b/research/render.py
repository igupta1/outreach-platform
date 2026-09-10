"""Headless-browser page fetch, with the regex path as the fallback.

`research/fetcher.py` strips HTML with a regex and executes no JavaScript. That
is fast (~200ms/page) and correct for server-rendered sites, and it returns
almost nothing for the React/Next/Vercel marketing sites most of these firms
run. Measured on graphadvisors.com, whose rendered pages say "VC funds, PE
firms, family offices" throughout:

    /                       56 chars
    /about                  21 chars
    /fractional-cfo         62 chars

The site is not thin -- one server-rendered page carries 10k chars, so it
clears THIN_MIN_CHARS. The damage is subtler and worse: Gate A requires a
stated phrase to appear VERBATIM on a fetched page, and the pages carrying the
claim come back empty. So the firm reads as a generalist not because it lacks a
specialty but because the sentence stating it was never downloaded.

This module does not relax that rule. Rendering only means more pages are
actually readable; the verbatim requirement is unchanged, and a phrase that
still cannot be found is still dropped.

`fetcher.fetch_site` calls back into this module as a fallback when its regex
fetch comes back under THIN_MIN_CHARS, so `run.py` now reads rendered pages
too on sites the no-JS fetch can't see. The corpus crawler uses this module
directly, with its own (higher) render threshold -- see `corpus/crawl.py`.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from system_b.research.fetcher import html_to_text

# Rendering is 10-25x slower than the regex path, so the budget is per page and
# firm. `networkidle` is the right wait for a marketing site: the content is
# there once XHR settles, and waiting for `load` alone returns the shell.
NAV_TIMEOUT_MS = 20_000
IDLE_TIMEOUT_MS = 6_000
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Chrome renders these too; blocking them cuts page time roughly in half and
# none of them can carry a stated vertical.
_BLOCKED = ("image", "media", "font", "stylesheet")


async def _render_one(context: Any, url: str) -> tuple[str, str]:
    """(html, error). Never raises -- a dead page is data, not a crash."""
    page = await context.new_page()
    try:
        await page.route("**/*", lambda route: asyncio.ensure_future(
            route.abort() if route.request.resource_type in _BLOCKED else route.continue_()
        ))
        await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
        except Exception:
            pass                      # settled enough; take what rendered
        return await page.content(), ""
    except Exception as exc:          # noqa: BLE001
        return "", f"{type(exc).__name__}"
    finally:
        await page.close()


async def render_pages(urls: list[str], *, concurrency: int = 4) -> dict[str, dict[str, str]]:
    """`{url: {"html":..., "text":..., "error":...}}` for a batch of URLs, one
    browser, N contexts. Callers own the batching."""
    from playwright.async_api import async_playwright

    out: dict[str, dict[str, str]] = {}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            sem = asyncio.Semaphore(concurrency)
            context = await browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})

            async def go(u: str) -> None:
                async with sem:
                    html, err = await _render_one(context, u)
                    out[u] = {"html": html, "text": html_to_text(html) if html else "", "error": err}

            await asyncio.gather(*(go(u) for u in urls))
            await context.close()
        finally:
            await browser.close()
    return out


def render_sync(urls: list[str], *, concurrency: int = 4) -> dict[str, dict[str, str]]:
    return asyncio.run(render_pages(urls, concurrency=concurrency))
