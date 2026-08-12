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

Output columns (one row per prospect): `email, first_name, last_name, company,
linkedin_url, subject, email_1, email_2, email_3, li_dm_1, li_dm_1_evergreen,
li_dm_2`. In Smartlead, build a 3-step sequence whose bodies are `{{email_1}}`,
`{{email_2}}`, `{{email_3}}`, and add your signature + the CAN-SPAM footer ONCE
in the sequence editor. Follow-ups have a blank subject so they thread off
email 1. Rows are ordered most-personalized first — the operator works the file
down and stops at LinkedIn's daily connection cap, so row order decides who gets
the second channel.

Set the history sheet up once with `python -m system_b.run --init-history`
(header only, and it refuses to overwrite a populated file).

Two companions land next to the CSV: `<out>.review.json` (the evidence, below)
and `<out>.new.csv` (only prospects no earlier run sequenced, for pasting onto
the outreach history sheet). The latter is backed by `--ledger`, a flat list of
every email ever written. It stores NO status: who accepted and who replied
lives in the hand-maintained sheet, so no tool can race the human editing it.

## The second channel (`copy/linkedin.py`)

Email is 3 of the 6 touches; the other 3 are LinkedIn (connection request, then
two DMs), pasted by hand — automating them is against LinkedIn's ToS and the
account is attached to a day job. The DM copy is templated here under the same
rules as the email: no model writes it, the vertical claim passes the same
`niche_claim` gate, every string is em-dash scrubbed.

**DM #1 ships in two shapes on every row.** The fresh one names a gift company
that "just posted" a role; the evergreen one names nothing that can go stale.
A connection request has no expiry, so an accept can land six weeks later, by
which time the fresh text asserts a role that closed — the same decay
`MAX_JOB_LEAD_AGE_DAYS` bounds on the email side, except a saved DM has no code
left to protect it. Use the evergreen past ~3 weeks. `build_dm_1` also falls
back to it whenever the best lead is not a job posting (a breach describes an
event, not an open role).

No DM references the email: while the sending mailboxes carry a name other than
the LinkedIn profile's, the prospect cannot connect the two.

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

## Lead quality gates (two layers, both drop-and-swap)

The inventory carries hundreds of leads per niche against ~100 prospects, so a
rejected lead costs a swap, never a gift. Both layers therefore DROP rather
than repair, and both log what they dropped.

- **Layer 1 — `clients/inventory.py`, at load.** Judges a lead alone, with no
  gift context: an ingest hash welded onto the name (`Lifesitenews 07Cfc`), no
  domain (the gift prints a name and a city and no link, so an uncheckable name
  reads as invented), or a posting whose own body names a DIFFERENT hiring
  company (a recruiter listing — the one error a recipient can catch outright).
- **Layer 2 — `gift/engine.py`, while building.** Judges a lead against the
  gift: one company per gift, matched on DOMAIN not name, because upstream
  dedup keys on the name and so misses exactly the duplicates that survive. A
  skipped duplicate is NOT added to `excluded` — that set is the used ledger,
  and marking an unused lead would silently shrink later gifts.

A "remote posting" check was considered and deliberately NOT built: `city`
always comes from the company's HQ (leadgen's `_split_location` returns None
for a remote posting, so the city is the enrichment answer), which means "a
company in denver needs finance help" stays true when the role is remote. It
would have dropped 12 accurate cfo leads for no honesty gain.

## Honesty invariants (do not weaken without explicit instruction)

- **Gate A (verbatim):** only claim a customer vertical the prospect stated
  word-for-word on their own site.
- **Gate B (fit):** only claim a niche when the gift's leads genuinely read as
  that vertical (taxonomy match AND an LLM value_prop fit check); otherwise drop
  to a generalist geo email. `value_prop` comes from the lead platform's
  published `insight` and is the ONLY field describing what a lead does. If it
  stops arriving, Gate B judges empty strings, answers false for every lead, and
  every run silently goes 100% generalist with no error and no flag — the
  2026-08-04 regression. A 0% niche rate means check `insight` in the blob
  FIRST. It feeds the gate only; it must never reach rendered copy.
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
