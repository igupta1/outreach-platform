"""One-off: register the Smartlead reply webhook against the DEPLOYED service.

  python -m system_b.scripts.register_webhook <campaign_id>

Reads WEBHOOK_PUBLIC_URL (e.g. https://your-service/webhooks/smartlead) and
WEBHOOK_TOKEN from the environment, registers EMAIL_REPLY + LEAD_UNSUBSCRIBED,
and exits. Run it once after the deploy (locally with the deploy's env, or from
a Railway/Render one-off shell). Unlike `webhook_server.py --register`, this does
NOT start a server.
"""

from __future__ import annotations

import sys

from system_b import config
from system_b.sending import SmartleadSender


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m system_b.scripts.register_webhook <campaign_id>")
        raise SystemExit(2)
    campaign_id = sys.argv[1]
    config.require("SMARTLEAD_API_KEY", "WEBHOOK_PUBLIC_URL")
    url = config.WEBHOOK_PUBLIC_URL
    if config.WEBHOOK_TOKEN and "token=" not in url:
        url += ("&" if "?" in url else "?") + f"token={config.WEBHOOK_TOKEN}"
    res = SmartleadSender().register_reply_webhook(campaign_id, url)
    print(f"registered webhook for campaign {campaign_id} -> {url}\n{res}")


if __name__ == "__main__":
    main()
