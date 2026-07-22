"""B5 CLI — serve the Smartlead reply webhook (Track H will absorb this later).

  system_b/.venv/bin/python -m system_b.scripts.webhook_server --port 8000

Expose it publicly (ngrok / a small host) and point Smartlead's EMAIL_REPLY
webhook at:  <public-url>/webhooks/smartlead?token=<WEBHOOK_TOKEN>

--register also registers that URL on a campaign via the Smartlead API.
"""

from __future__ import annotations

import argparse

from system_b import config


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the Smartlead reply webhook.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--register", metavar="CAMPAIGN_ID", default=None,
                    help="register WEBHOOK_PUBLIC_URL on this campaign, then serve")
    args = ap.parse_args()

    if args.register:
        config.require("SMARTLEAD_API_KEY", "WEBHOOK_PUBLIC_URL")
        from system_b.sending import SmartleadSender
        url = config.WEBHOOK_PUBLIC_URL
        if config.WEBHOOK_TOKEN and "token=" not in url:
            url += ("&" if "?" in url else "?") + f"token={config.WEBHOOK_TOKEN}"
        res = SmartleadSender().register_reply_webhook(args.register, url)
        print(f"[register] campaign {args.register} -> {url}: {res}")

    import uvicorn
    print(f"[serve] http://{args.host}:{args.port}/webhooks/smartlead  (token guard: "
          f"{'on' if config.WEBHOOK_TOKEN else 'OFF — set WEBHOOK_TOKEN'})")
    uvicorn.run("system_b.webhooks.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
