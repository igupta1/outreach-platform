"""Approval CLI (stands in for the Track H review screen). Approve pushes the
queued draft to Smartlead (first touch adds the lead; a follow-up updates the
{{email_2/3}} variable). Reject -> do_not_contact. Edit stores a fixed message.

  ... scripts.approve --record recXXXX --action approve
  ... scripts.approve --record recXXXX --action edit --message "Subject: ..\n\nhey.."
  ... scripts.approve --record recXXXX --action reject
"""

from __future__ import annotations

import argparse

from system_b import config
from system_b.clients.airtable_client import AirtableClient
from system_b.review import apply_decision
from system_b.sequence import approve_and_send


def main() -> None:
    ap = argparse.ArgumentParser(description="Approve / edit / reject a queued draft.")
    ap.add_argument("--record", required=True, help="Airtable record id")
    ap.add_argument("--action", required=True, choices=["approve", "edit", "reject"])
    ap.add_argument("--message", default=None, help="edited queued_message (edit/approve)")
    args = ap.parse_args()

    config.require("AIRTABLE_TOKEN", "AIRTABLE_BASE_ID")
    at = AirtableClient()

    if args.action == "approve":
        config.require("SMARTLEAD_API_KEY")
        from system_b.sending import SmartleadSender
        res = approve_and_send(at, SmartleadSender(), args.record, edited_message=args.message)
        print(f"[sent] step {res['step']} -> stage {res['stage']} (lead {res['lead_id']})")
    else:
        apply_decision(at, args.record, args.action, edited_message=args.message)
        print(f"[{args.action}] applied to {args.record}")
    at.close()


if __name__ == "__main__":
    main()
