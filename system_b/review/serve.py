"""Serve the review gate — ONE local page over every pack's review JSON.

    system_b/.venv/bin/python -m system_b.review.serve \
        --review cfo.review.json acct.review.json book.review.json

Open the printed URL, read each prospect's evidence, edit any copy that looks
off, then download. Everything after load is client-side; this server only
serves the page. It is read-only and send-free — no CRM, no Airtable, no send.

## Why one page for every pack

The packs are generated separately because each needs its own `--pack` voice,
but the operator's day is not divided that way. Three pages meant three sorted
lists and three separate answers to a question that has one: **who do I send a
connection request to today?** LinkedIn's cap is one budget across everything
running, so the top 20 has to be chosen across every pack at once — and the
only place that decision can be made is where all three are on screen together.

So the page groups by pack (each with its own header and its own email
download, because each goes to a different campaign) while ranking the connect
picks GLOBALLY. A bookkeeping prospect with named clients outranks a cfo
prospect matched only on state, and now you can see that.

The email CSVs stay separate — one per campaign. The LinkedIn CSV is COMBINED,
because it all gets pasted into one history sheet that is searched by name
weeks later, when someone finally accepts.

The JSON files are re-read on every request, so you can regenerate (`run.py`)
and just refresh the page.
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_PAGE = Path(__file__).with_name("page.html")


def load_packs(paths: list[Path]) -> dict[str, Any]:
    """Merge every review JSON into one document the page can render.

    Order is the order given on the command line, which is the order the packs
    were run in — and that is also the precedence order the ledger applied, so
    the page reads the same way the day did.

    A file that cannot be read is reported in `errors` and skipped rather than
    raising: one bad path must not cost you the rest of the review.
    """
    packs: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        packs.append({
            "pack": doc.get("pack") or path.stem,
            "generated_at": doc.get("generated_at") or "",
            "skipped": doc.get("skipped") or [],
            "prospects": doc.get("prospects") or [],
            "source": path.name,
        })
    return {"packs": packs, "errors": errors}


def render(review_paths: list[Path]) -> bytes:
    """The page HTML with every pack's review JSON inlined. Reads all files
    fresh so a regenerate + browser refresh shows the new run."""
    data = load_packs(review_paths)
    # Escape `<` so nothing in the copy (e.g. a stray "</script>") can break out
    # of the inline <script>. json.dumps already escapes the other specials.
    blob = json.dumps(data).replace("<", "\\u003c")
    html = _PAGE.read_text(encoding="utf-8")
    return html.replace("__REVIEW_DATA__", blob).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, review_paths: list[Path], **kwargs):
        self.review_paths = review_paths
        super().__init__(*args, **kwargs)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler naming
        if self.path.split("?", 1)[0] in ("/", "/index.html"):
            try:
                body = render(self.review_paths)
            except FileNotFoundError:
                self._send(404, b"page.html not found", "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # keep the console clean
        pass


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Serve the outreach review gate.")
    ap.add_argument("--review", nargs="+", default=["sequences.review.json"],
                    help="review JSON emitted by run.py — pass one per pack, in "
                         "the order you ran them")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)

    paths = [Path(p).resolve() for p in args.review]
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(
            "review file(s) not found:\n"
            + "\n".join(f"  {p}" for p in missing)
            + "\n\ngenerate them first, e.g.:\n"
              "  python -m system_b.run --in FractionalCFO.csv --out cfo.out.csv --pack cfo"
        )

    handler = partial(Handler, review_paths=paths)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    names = ", ".join(p.name for p in paths)
    print(f"[review] serving {len(paths)} pack file(s) at {url}  (Ctrl-C to stop)")
    print(f"[review] {names}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[review] stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
