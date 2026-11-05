"""Serve the review gate — ONE local page over every pack's review JSON.

    system_b/.venv/bin/python -m system_b.review.serve \
        --review cfo.review.json acct.review.json book.review.json

Open the printed URL, read each prospect's evidence, edit any copy that looks
off, then download. Everything after load is client-side; this server serves
the page and records which addresses a download carried (POST /downloaded,
a local file beside the batch, read by the nightly job so a batch you never
download goes back on the queue). It is send-free — no CRM, no Airtable, no send.

## Why one page for every pack

The packs are generated separately because each needs its own `--pack` voice,
but the operator reviews the whole day at once. The page groups by pack (each
with its own email download) and the footer exports every pack as one file for
a single campaign. The gate is email-only: LinkedIn is not used for these
prospects (2026-10-24).

The JSON files are re-read on every request, so you can regenerate (`run.py`)
and just refresh the page.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
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
            "checks": doc.get("checks") or None,
            "source": path.name,
        })
    return {"packs": packs, "errors": errors}


def _clock(t: datetime) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def _span(a: datetime, b: datetime) -> str:
    """2:00–3:50 am; 11:40 pm–1:05 am"""
    x, y = _clock(a), _clock(b)
    return f"{x[:-3]}–{y}" if x[-2:] == y[-2:] else f"{x}–{y}"


def _pid_alive(lock: Path) -> bool:
    try:
        os.kill(int(lock.read_text().strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def nightly_status(logs: Path, now: datetime | None = None) -> dict[str, str] | None:
    """The one line at the top of the page: is this morning's batch ready?

    Read from logs/nightly-status.json (written by `system_b.nightly`).
    {"kind": "ok" | "wait" | "bad", "text": ...}, or None when the nightly job
    has never run here. A batch older than tonight's 02:00 run is "not ready":
    the page then still shows it, but says it is the old one."""
    try:
        st = json.loads((logs / "nightly-status.json").read_text())
    except (OSError, ValueError):
        return None
    now = now or datetime.now()
    # The night the page should be showing: today's after 02:00, else yesterday's.
    due = now.date() if now.hour >= 2 else now.date() - timedelta(days=1)
    try:
        night = date.fromisoformat(st.get("night") or "")
        started = datetime.fromisoformat(st["started"])
        finished = datetime.fromisoformat(st["finished"]) if st.get("finished") else None
    except (KeyError, ValueError):
        return {"kind": "bad", "text": "Not ready: the nightly status file is unreadable; see logs/nightly.log"}
    state = st.get("state")
    if state == "building":
        if _pid_alive(logs / ".nightly.lock"):
            return {"kind": "wait", "text": f"Not ready yet: building now (started {_clock(started)})"}
        return {"kind": "bad", "text": f"Not ready: the run that started {_clock(started)} stopped "
                                       "partway; see logs/nightly.log"}
    if night < due:
        last = f"{night:%b} {night.day}"
        return {"kind": "bad", "text": f"Not ready: tonight's run has not happened (Mac asleep or off?). "
                                       f"This is the batch from {last}" if state == "ready" else
                                       f"Not ready: no run since {last}"}
    if state == "ready":
        text = f"Ready · {st.get('emails', 0)} emails · built {_span(started, finished or started)}"
        if st.get("fix"):
            text += f" · {st['fix']} to fix"
        return {"kind": "ok", "text": text}
    tail = f" · next try {st['next_try']}" if st.get("next_try") else " · no more tries tonight"
    return {"kind": "bad", "text": f"Not ready: {st.get('reason') or 'the run failed'}{tail}"}


def render(review_paths: list[Path]) -> bytes:
    """The page HTML with every pack's review JSON inlined. Reads all files
    fresh so a regenerate + browser refresh shows the new run."""
    data = load_packs(review_paths)
    data["status"] = nightly_status(review_paths[0].resolve().parent / "logs")
    # Escape `<` so nothing in the copy (e.g. a stray "</script>") can break out
    # of the inline <script>. json.dumps already escapes the other specials.
    blob = json.dumps(data).replace("<", "\\u003c")
    html = _PAGE.read_text(encoding="utf-8")
    return html.replace("__REVIEW_DATA__", blob).encode("utf-8")


def downloaded_path(review_path: Path) -> Path:
    """sequences.review.json -> sequences.downloaded.json"""
    return review_path.with_name(review_path.name.replace(".review.json", "") + ".downloaded.json")


def record_download(review_path: Path, emails: list[str]) -> None:
    """Add these addresses to the batch's download record (a union: several
    downloads, or one per pack, all count)."""
    path = downloaded_path(review_path)
    seen: list[str] = []
    if path.exists():
        try:
            seen = list(json.loads(path.read_text()).get("emails") or [])
        except (OSError, ValueError):
            seen = []
    merged = list(dict.fromkeys(seen + [e.strip().lower() for e in emails if e.strip()]))
    path.write_text(json.dumps({"emails": merged}, indent=1))


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

    def do_POST(self) -> None:  # noqa: N802
        """The one write: which addresses a download carried, so the nightly
        job knows which prospects were sent (`system_b.nightly`). Local file
        beside the batch; no send, no CRM. Anything else is a 404."""
        if self.path.split("?", 1)[0] != "/downloaded":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            emails = json.loads(self.rfile.read(min(n, 2_000_000)) or b"{}").get("emails") or []
            record_download(self.review_paths[0], [str(e) for e in emails])
        except (ValueError, OSError):
            self._send(400, b"bad request", "text/plain; charset=utf-8")
            return
        self._send(204, b"", "text/plain; charset=utf-8")

    def log_message(self, *args) -> None:  # keep the console clean
        pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Serve the outreach review gate.")
    ap.add_argument("--review", nargs="+", default=["sequences.review.json"],
                    help="review JSON emitted by run.py — pass one per pack, in "
                         "the order you ran them")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    paths = [Path(p).resolve() for p in args.review]
    missing = [p for p in paths if not p.exists()]
    if missing:
        # Serve anyway: the always-on gate (ops/com.outreach.review.plist) must
        # be up while the nightly batch is being built, to say so.
        print("[review] not there yet (the page says why):\n"
              + "\n".join(f"  {p}" for p in missing))

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
