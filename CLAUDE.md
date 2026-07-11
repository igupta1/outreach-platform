# CLAUDE.md

Cold-outreach engine. Python, isolated from the website and the lead pipelines
(talks to the lead inventory over HTTP, writes Airtable).

## Layout

- `system_b/` — the engine. The gift builder (`gift/`) and copy scaffolding
  (`copy/`) are niche-blind; every buyer-specific knob (signal vocabulary,
  priority signal, copy voice) lives in a `NichePack` under `system_b/niches/`.
  Core functions take `pack=None` and lazily default to the CFO pack, so a new
  buyer is added purely as a new pack — no edits to core logic.
- `system_b/niches/` — the packs: `cfo.py` (fractional CFO, the default) and
  `trucking.py` (commercial trucking insurance; also holds the adapter that maps
  the insurance pipeline's `trucking-leads.json` onto the outreach `Lead`).
  Trucking matches on geography only (agents are state-licensed) via the engine's
  existing generalist path — no site research needed.
- Conventions: see `system_b/` — everything structural is deterministic code;
  the LLM only proposes (site classification, lead-fit check, per-lead
  descriptions) and code re-verifies. Honesty is enforced in code, never left
  to the model.

## Honesty invariants (do not weaken without explicit instruction)

- **Gate A (verbatim):** only claim an industry the prospect stated word-for-word
  on their own site.
- **Gate B (fit):** only claim a niche when the gift's leads genuinely read as
  that niche (taxonomy match AND an LLM value_prop fit check); otherwise drop to
  a generalist geo email.
- Framing uses the clean mapped niche word, never the raw scraped phrase.
- Soft verb ("work with"), never "focus on".
- No dollar amounts on raises; relative dates only for high-confidence signals;
  lead company names keep their casing, all other prose is lowercase.
- Nothing is ever sent automatically — every card is `review_status=pending`.

## Forbidden without explicit instruction

- Committing `.env`, `apollo-contacts-export.csv`, or `review_cards.txt`.
- Wholesale-destructive ops (`rm -rf` of dirs, `git reset --hard`, force push,
  dropping/truncating data, mass file deletes). Single-file deletes are fine.
