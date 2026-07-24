# outreach-platform

Cold-outreach copy generator. One job, three steps:

1. **Upload** an Apollo contacts export (CSV).
2. **Generate** — for each prospect, research their site and build a gift of real
   companies (from the `leadgen` lead inventory) that fit the vertical they
   serve, then write an honest, personalized 3-email sequence.
3. **Review** — get a CSV of every email + follow-up to read before you send.

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

## Lead inventory source (stub vs live)

The gift companies come from the `leadgen` platform via `clients/inventory.py`
(`snapshot_for_niche`):

- **Stub:** set `LEADGEN_INVENTORY_DIR` to a folder of `leadgen` output
  (`<niche>-leads.json` + `taxonomy.json`) to run fully offline.
- **Live:** unset it, and the client reads the website's per-niche inventory
  endpoint. Secrets live in `system_b/.env` (gitignored — never commit).

## Pipeline (per prospect)

research the firm's site → classify the customer vertical they serve (only
claims stated verbatim on their own site) → build a gift of ~3 companies whose
signals genuinely fit that vertical (or fall back to a generalist geo gift) →
write casual, honesty-checked copy → emit the CSV row.
