# outreach-platform

Cold-outreach copy generator. One job, three steps:

1. **Upload** an Apollo contacts export (CSV).
2. **Generate** — for each prospect, research their site and build a gift of real
   companies (from the `leadgen` lead inventory) that fit the vertical they
   serve, then write an honest, personalized 3-email sequence.
3. **Review** — read every email + follow-up before you send, either straight
   from the output CSV or in the local review gate (below), then upload the CSV.

Nothing is sent automatically. You upload the output CSV to Smartlead (or any
sequencer) yourself.

## Run

```bash
cd system_b
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in OPENAI_API_KEY

# run from the repo ROOT (running inside system_b/ shadows stdlib `copy`):
cd .. && system_b/.venv/bin/python -m system_b.run \
    --in system_b/apollo-contacts-export.csv --out sequences.csv --pack cfo
```

`--pack` is one of the five niches (`accounting`, `cfo`, `mssp`, `msp`, `cloud`)
and applies to the whole run — it sets the voice and which lead signals count as
a good gift. Run once per Apollo list.

### Output

One row per prospect:

```
email, first_name, company, subject, email_1, email_2, email_3
```

In Smartlead/Instantly, build a 3-step sequence whose step bodies are just
`{{email_1}}`, `{{email_2}}`, `{{email_3}}`, and add your signature + opt-out
footer ONCE in the sequence editor. Follow-ups have a blank subject so they
thread off email 1.

## Review gate (optional)

Each run also writes `<out>.review.json` with the evidence behind every
sequence. Open the local review page to check it before importing to Smartlead:

```bash
system_b/.venv/bin/python -m system_b.review.serve --review sequences.review.json
# then open the printed http://127.0.0.1:8000
```

One page, one row per valid prospect: how we classified their niche (the
verbatim phrase + the URL it was found on), the gift leads with each one's
signal, plain-words evidence, date, domain, and **source link**, and any honesty
flags to double-check. The subject and three email bodies are editable inline; a
**Download CSV** button at the bottom rebuilds the exact output CSV from your
edits. Fully local and send-free — it never sends or stores anything.

## Lead inventory source (blob vs local)

The gift companies come from the `leadgen` platform via `clients/inventory.py`
(`snapshot_for_niche`):

- **Blob (primary):** set `LEADGEN_BLOB_BASE_URL` to the lead platform's public
  Vercel Blob base. The client reads `<base>/<niche>-leads.json` directly — the
  daily-fresh inventory `leadgen` publishes every night. No auth, no website.
- **Local (offline fallback):** unset the blob URL and set `LEADGEN_INVENTORY_DIR`
  to a folder of `leadgen` output (`<niche>-leads.json` + `taxonomy.json`).

Either way a freshness guard refuses inventory older than
`LEADGEN_MAX_INVENTORY_AGE_DAYS` (default 3 days) unless `LEADGEN_ALLOW_STALE=1`,
so you never generate against stale gifts by accident. Config lives in
`system_b/.env` (gitignored — never commit).

## Pipeline (per prospect)

research the firm's site → classify the customer vertical they serve (only
claims stated verbatim on their own site) → build a gift of ~3 companies whose
signals genuinely fit that vertical (or fall back to a generalist geo gift) →
write casual, honesty-checked copy → emit the CSV row.
