"""Serve the review gate — one plain local web page over the run's review JSON.

    system_b/.venv/bin/python -m system_b.review.serve --review sequences.review.json

Open the printed URL, read each prospect's evidence, edit any copy that looks
off, then click "Download CSV" at the bottom to get the exact Smartlead CSV
(email, first_name, company, subject, email_1, email_2, email_3) built from
whatever you edited. Everything after load is client-side; this server only
serves the page. It is read-only and send-free — no CRM, no Airtable, no send.

The JSON is re-read on every request, so you can regenerate (`run.py`) and just
refresh the page.
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_PAGE = Path(__file__).with_name("page.html")


def render(review_path: Path) -> bytes:
    """The page HTML with the review JSON inlined. Reads both files fresh so a
    regenerate + browser refresh shows the new run."""
    data = json.loads(review_path.read_text(encoding="utf-8"))
    # Escape `<` so nothing in the copy (e.g. a stray "</script>") can break out
    # of the inline <script>. json.dumps already escapes the other specials.
    blob = json.dumps(data).replace("<", "\\u003c")
    html = _PAGE.read_text(encoding="utf-8")
    return html.replace("__REVIEW_DATA__", blob).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, review_path: Path, **kwargs):
        self.review_path = review_path
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
                body = render(self.review_path)
            except FileNotFoundError:
                self._send(404, f"review file not found: {self.review_path}".encode(),
                           "text/plain; charset=utf-8")
                return
            self._send(200, body, "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # keep the console clean
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the outreach review gate.")
    ap.add_argument("--review", default="sequences.review.json",
                    help="review JSON emitted by run.py")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    review_path = Path(args.review).resolve()
    if not review_path.exists():
        raise SystemExit(f"review file not found: {review_path}\n"
                         f"generate it first with: python -m system_b.run --in <apollo.csv> --out sequences.csv")

    handler = partial(Handler, review_path=review_path)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}"
    print(f"[review] serving {review_path.name} at {url}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[review] stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
