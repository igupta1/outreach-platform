# CLAUDE.md

Cold-outreach copy generator. Python, isolated from the website and the lead
platform (reads the lead inventory over HTTP / from local JSON). One job:

    Apollo CSV in → a 3-email sequence per prospect → review CSV out.

Nothing is sent. You upload the output CSV to Smartlead yourself.

## The one command

```bash
cd system_b
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in OPENAI_API_KEY

# run from the repo ROOT (running inside system_b/ shadows stdlib `copy`):
cd .. && system_b/.venv/bin/python -m system_b.run \
    --in system_b/apollo-contacts-export.csv --out sequences.csv --pack cfo
```

Output columns (one row per prospect): `email, first_name, company, subject,
email_1, email_2, email_3`. In Smartlead, build a 3-step sequence whose bodies
are `{{email_1}}`, `{{email_2}}`, `{{email_3}}`, and add your signature + the
CAN-SPAM footer ONCE in the sequence editor. Follow-ups have a blank subject so
they thread off email 1.

## Review gate (optional, local, send-free)

`run.py` also writes `<out>.review.json` — the evidence the CSV drops (niche
classification + the verbatim phrase/URL it came from, each gift lead's signal /
plain-words line / date / domain / **source_url**, and the honesty flags), plus
the editable copy. Review it in the browser before Smartlead:

```bash
cd .. && system_b/.venv/bin/python -m system_b.review.serve --review sequences.review.json
```

One plain page: the count of valid prospects, each one's evidence, and editable
subject/email_1/email_2/email_3 fields, with a client-side **Download CSV**
button at the bottom that rebuilds the exact output CSV (byte-identical to
`run.py`'s) from whatever you edited. It is read-only + client-side + send-free —
it never sends, stores CRM state, or talks to Airtable. `system_b/review/`.

## Layout (`system_b/`)

- `run.py` — the whole pipeline CLI (CSV → CSV). One niche pack per run (`--pack`).
- `prospects.py` — reads the Apollo export into the flat prospect row.
- `sequence/generate.py` — `generate_sequence(row, …)`: research → gift → the
  full 3-email sequence, returned as a plain dict. **Pure** — no store, no send.
- The engine is **niche-blind**; every buyer-specific knob (signal preference,
  priority signal, copy voice) lives in a `NichePack` under `niches/`.
  - `gift/` builds a vertical-matched gift from the lead inventory (or a
    generalist geo gift).
  - `copy/` writes the emails; `research/` classifies the prospect's site;
    `sequence/` assembles the 3 emails.
- `clients/inventory.py` — the single adapter from the `leadgen` per-niche
  inventory (`snapshot_for_niche`) onto the outreach `Lead`. Source: env
  `LEADGEN_BLOB_BASE_URL` set → read `<base>/<niche>-leads.json` from the lead
  platform's PUBLIC Vercel Blob (daily-fresh, no auth, no website); else
  `LEADGEN_INVENTORY_DIR` → local JSON (offline). A freshness guard refuses
  inventory older than `LEADGEN_MAX_INVENTORY_AGE_DAYS` (default 3) unless
  `LEADGEN_ALLOW_STALE=1`, so a broken daily refresh can't ship stale gifts.
- Conventions: ALL copy is deterministic code. Every lead line is templated
  (hiring, breach), so no model writes any part of a sent email — `copy/llm.py`
  was deleted (2026-08-04). The LLM only proposes site classification and the
  lead-fit check, and code re-verifies. Honesty is enforced in code.
- A job lead older than `config.MAX_JOB_LEAD_AGE_DAYS` (21) never enters a
  gift: the copy says a company "is looking for" a role in the present tense,
  and a closed posting makes that false with no way for the recipient to tell.

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
- **No em dashes anywhere.** Templates are authored comma-only, and every
  rendered subject + body is run through `copy.honesty.strip_em_dashes` so a
  dash from lead source data (`insight`/`evidence_text`) can't reach a sent
  email either. Do not remove that scrub.
- Nothing is ever sent — the tool only writes a CSV for you to review.

## Forbidden without explicit instruction

- Committing `.env` or `apollo-contacts-export.csv` (or any `sequences*.csv`).
- Re-adding sending (Smartlead), Airtable/CRM state, the operator web UI/API,
  reply webhooks, or notifications — all removed; this is a CSV→CSV batch tool.
  (The local `system_b/review` gate is the one sanctioned exception: it is
  read-only, client-side, and send-free — do NOT grow it into a sender, a CRM,
  or a hosted service.)
- Re-adding an insurance/trucking/pc niche, an `exec_hired` signal, or the old
  `cfo_wanted`/`funding_only`/`hiring_only` collapsed signal vocabulary.
- Re-adding a raise/funding claim (`funding_phrase`, `raise_signals`) — the
  EDGAR sources that evidenced it were deleted, so the claim is unprovable.
- Letting a model write any part of a lead line.
- Wholesale-destructive ops (`rm -rf` of dirs, `git reset --hard`, force push,
  dropping/truncating data, mass file deletes). Single-file deletes are fine.
