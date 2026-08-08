"""The review gate — a local, offline, send-free review step between generation
and the final CSV.

`generate_sequence` attaches a `review` payload (see `payload.build_review`) to
every prospect it drafts; `run.py` dumps those payloads to `<out>.review.json`.
`serve.py` then serves one plain web page that shows the count of valid
prospects, each one's evidence (how we classified the niche + the gift leads
with their source links) and its editable copy, with a client-side "Download
CSV" button that rebuilds the exact Smartlead CSV from whatever you edited.

Nothing here sends, stores CRM state, or talks to Airtable — it only reads the
generated JSON, lets you edit copy, and re-exports the CSV.
"""

from __future__ import annotations

from system_b.review.payload import build_review

__all__ = ["build_review"]
