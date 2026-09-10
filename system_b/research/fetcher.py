"""Fetch a prospect's website: Home + About/Industries/Who-We-Serve/Case
Studies/Clients. HTML->text and link discovery are pure functions (tested);
fetch_site does the network I/O (guarded, best-effort).

No bs4 dependency — a small regex HTML stripper is enough for classifying
prose and pulling anchor hrefs.
"""

from __future__ import annotations

import html as _html
import re
from urllib.parse import urljoin, urlparse

import httpx

from system_b.research.classifier import THIN_MIN_CHARS

# Subpages worth reading, matched against href path + anchor text (Step 2).
_PAGE_KEYWORDS = (
    "about", "industr", "who-we-serve", "whoweserve", "who_we_serve",
    "client", "case-stud", "casestud", "case_stud", "work", "portfolio",
    "sector", "vertical", "expertise", "practice", "services", "markets",
)
_MAX_PAGES = 6
_FETCH_TIMEOUT = 15.0
_UA = "Mozilla/5.0 (compatible; SystemB-research/1.0)"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_WS_RE = re.compile(r"\s+")
_ANCHOR_RE = re.compile(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)


def html_to_text(source: str) -> str:
    """Strip HTML to visible text: drop script/style/comments, unwrap tags,
    unescape entities, collapse whitespace."""
    s = _COMMENT_RE.sub(" ", source)
    s = _SCRIPT_STYLE_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    s = _html.unescape(s)
    return _WS_RE.sub(" ", s).strip()


def discover_links(source: str, base_url: str) -> list[str]:
    """Same-site subpage URLs worth reading, in first-seen order, capped."""
    base_host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    out: list[str] = []
    for href, inner in _ANCHOR_RE.findall(source):
        text = html_to_text(inner).lower()
        hay = f"{href.lower()} {text}"
        if not any(k in hay for k in _PAGE_KEYWORDS):
            continue
        url = urljoin(base_url, href.split("#")[0]).rstrip("/")
        if not url or urlparse(url).netloc.lower() not in ("", base_host):
            continue
        if url == base_url.rstrip("/") or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= _MAX_PAGES:
            break
    return out


def _render_fallback(url: str) -> dict[str, str]:
    """Render homepage + discovered subpages when the regex path came back
    thin. Discovery runs on the RENDERED dom, same as the corpus crawler --
    a nav built by JavaScript is invisible to the regex path, which is part of
    why it finds so little. Never raises; an empty dict means "no better than
    the regex path", not an error."""
    from system_b.research.render import render_sync

    home = render_sync([url], concurrency=1)
    home_html = home.get(url, {}).get("html", "")
    if not home_html:
        return {}
    pages = {url.rstrip("/"): home_html}
    subs = discover_links(home_html, url)
    if subs:
        rendered = render_sync(subs, concurrency=3)
        for u, r in rendered.items():
            if r.get("html"):
                pages[u] = r["html"]
    return {u: html_to_text(h) for u, h in pages.items()}


def fetch_site(url: str) -> dict[str, str]:
    """Best-effort {url: text} for the homepage + discovered subpages. Any
    failure (bad URL, network error, unreachable site) yields {} or a partial
    map, which the classifier treats as a thin site -> generalist. Never raises.

    Regex first, always -- it's ~200ms/page and correct for server-rendered
    sites. Only when that comes back under THIN_MIN_CHARS (the classifier's own
    generalist floor) do we pay for a headless render, and only keep it if it
    actually reads more than the regex path did. Gate A's verbatim rule is
    unchanged either way -- rendering just means more pages are readable for it
    to check a claim against."""
    site: dict[str, str] = {}
    if not url or not url.lower().startswith(("http://", "https://")):
        return site  # e.g. an email address in the Website column
    try:
        with httpx.Client(
            timeout=_FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            home = client.get(url)
            home.raise_for_status()
            home_html = home.text
            site[url.rstrip("/")] = html_to_text(home_html)
            for sub in discover_links(home_html, url):
                try:
                    r = client.get(sub)
                    r.raise_for_status()
                    site[sub] = html_to_text(r.text)
                except Exception:
                    continue
    except Exception:
        return site

    if sum(len(v) for v in site.values()) < THIN_MIN_CHARS:
        try:
            rendered = _render_fallback(url)
        except Exception:
            rendered = {}
        if sum(len(v) for v in rendered.values()) > sum(len(v) for v in site.values()):
            return rendered
    return site
