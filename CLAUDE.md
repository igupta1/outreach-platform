# CLAUDE.md

Cold-outreach engine. Python, isolated from the website and the lead platform
(reads the lead inventory over HTTP, writes Airtable).

## Layout

- `system_b/` — the engine. The gift builder (`gift/`), copy scaffolding
  (`copy/`), research (`research/`), and sequencing (`sequence/`) are
  **niche-blind**; every buyer-specific knob (signal preference, priority
  signal, copy voice) lives in a `NichePack` under `system_b/niches/`.
- **One unified pipeline for all five niches** (`accounting`, `cfo`, `mssp`,
  `msp`, `cloud`): research the prospect's site → classify the customer vertical
  they serve (verbatim, Gate A) → `resolve_gift` builds a vertical-matched gift
  (Gate B) or falls back to a generalist geo gift → LLM per-lead descriptions →
  a pending review card. A niche differs ONLY in its pack (lead preference,
  priority signal, copy voice) — same engine, same gates, same cadence.
- `system_b/niches/` — the five packs: `cfo.py` (default), `accounting.py`,
  `it_provider.py` (`msp`/`mssp`/`cloud`). Resolved by `base.pack_for(key)`.
- `system_b/clients/inventory.py` — the single adapter from the `leadgen`
  per-niche inventory (`snapshot_for_niche`) onto the outreach `Lead`. Signal
  types are leadgen's raw vocabulary (`job_fractional_cfo`, `job_finance_lead`,
  `job_junior_finance`, `job_it_support`, `job_it_leadership`, `job_security`,
  `job_cloud_devops`, `funding_form_d`, `funding_form_c`, `breach_disclosed`).
  Stub mode: env `LEADGEN_INVENTORY_DIR` → local JSON; else the live endpoint.
- Conventions: everything structural is deterministic code; the LLM only
  proposes (site classification, lead-fit check, per-lead descriptions) and code
  re-verifies. Honesty is enforced in code, never left to the model.

## Honesty invariants (do not weaken without explicit instruction)

- **Gate A (verbatim):** only claim a customer vertical the prospect stated
  word-for-word on their own site.
- **Gate B (fit):** only claim a niche when the gift's leads genuinely read as
  that vertical (taxonomy match AND an LLM value_prop fit check); otherwise drop
  to a generalist geo email.
- Framing uses the clean mapped niche word, never the raw scraped phrase.
- Soft verb ("work with"), never "focus on".
- No dollar amounts on raises; relative dates only for high-confidence signals;
  lead company names keep their casing, all other prose is lowercase.
- Nothing is ever sent automatically — every card is `review_status=pending`.

## Forbidden without explicit instruction

- Committing `.env`, `apollo-contacts-export.csv`, or `review_cards.txt`.
- Re-adding an insurance/trucking/pc niche, an `exec_hired` signal, or the old
  `cfo_wanted`/`funding_only`/`hiring_only` collapsed signal vocabulary (all
  removed in the leadgen migration).
- Wholesale-destructive ops (`rm -rf` of dirs, `git reset --hard`, force push,
  dropping/truncating data, mass file deletes). Single-file deletes are fine.
