"""Run the Track H operator service locally.

  system_b/.venv/bin/python -m system_b.scripts.serve --port 8000
  system_b/.venv/bin/python -m system_b.scripts.serve --no-scheduler   # safe poking

--no-scheduler disables the background timing guard (which would otherwise call
Smartlead/Airtable on startup) — use it before the campaign is wired.
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the operator API + webhook.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-scheduler", action="store_true",
                    help="disable the background timing-guard loop (safe local poking)")
    args = ap.parse_args()

    if args.no_scheduler:
        # Read by config before the app module builds its module-level app.
        os.environ["SCHEDULER_ENABLED"] = "0"

    import uvicorn
    print(f"[serve] http://{args.host}:{args.port}  "
          f"(scheduler: {'off' if args.no_scheduler else 'on'})")
    uvicorn.run("system_b.api.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
