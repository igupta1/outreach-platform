# outreach-platform

Multi-niche cold-outreach engine. Takes a buyer's prospect list + a live lead
inventory and produces honest, personalized outreach — one review card per
prospect, nothing sent automatically.

`system_b/` runs **one unified pipeline for all five niches** — `accounting`,
`cfo`, `mssp`, `msp`, `cloud`:

- **`core` (niche-blind):** prospect research, verbatim-evidence classification,
  the two honesty gates, gift building, copy scaffolding, review cards,
  CRM/Airtable state.
- **`niches/<buyer>.py`:** thin per-buyer packs — voice, which lead signals
  count as a good gift (lead preference + priority signal), framing/copy.

## Pipeline (per prospect, every niche)

research the firm's site → classify the customer vertical they serve (only
claims stated verbatim on their own site) → build a gift of ~3 companies whose
signals genuinely fit that vertical (or fall back to a generalist geo gift) →
write casual, honesty-checked copy → assemble a review card into Airtable at
`review_status=pending`.

The lead inventory comes from the `leadgen` platform via
`clients/inventory.py` (`snapshot_for_niche`), in the raw signal vocabulary
(`job_fractional_cfo`, `job_finance_lead`, `job_junior_finance`, `job_it_support`,
`job_it_leadership`, `job_security`, `job_cloud_devops`, `funding_form_d`,
`funding_form_c`, `breach_disclosed`).

```bash
cd system_b
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in AIRTABLE_TOKEN, OPENAI_API_KEY, etc.

# run from the repo ROOT (running inside system_b/ shadows stdlib `copy`):
cd .. && system_b/.venv/bin/python -m pytest system_b/tests -q
```

## Inventory source (stub vs live)

- **Stub:** set `LEADGEN_INVENTORY_DIR` to a folder of `leadgen` output
  (`<niche>-leads.json` + `taxonomy.json`) to run fully offline.
- **Live:** unset it, and the client reads the website's per-niche inventory
  endpoint. Secrets live in `system_b/.env` (gitignored — never commit).

Nothing is ever sent automatically — every card is `review_status=pending`.
