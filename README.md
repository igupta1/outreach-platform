# outreach-platform

Multi-niche cold-outreach engine. Takes a buyer's prospect list + a live lead
inventory and produces honest, personalized outreach — one review card per
prospect, nothing sent automatically.

`system_b/` is the first implementation, built for **fractional CFOs**. It is
the reference for the planned generalization:

- **`core/`** — the reusable engine: prospect research, verbatim-evidence
  classification, the two honesty gates, gift building, copy scaffolding,
  review cards, CRM/Airtable state.
- **`niches/<buyer>/`** — thin per-buyer packs: voice, which lead signals count
  as a good gift, framing/copy, and the prospect-list source.

## System B (current: fractional CFO pack)

Pipeline per prospect: research the firm's site → classify what they work with
(only claims stated verbatim on their own site) → build a gift of ~3 companies
whose signals genuinely fit → write casual, honesty-checked copy → assemble a
review card into Airtable at `review_status=pending`.

```bash
cd system_b
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in AIRTABLE_TOKEN, OPENAI_API_KEY, etc.
python -m pytest tests/ -q
```

Full walkthrough (research → gift → draft → card, sends nothing):

```bash
python -m system_b.scripts.m4_walkthrough --csv system_b/apollo-contacts-export.csv --summary
python -m system_b.scripts.dump_cards --out system_b/review_cards.txt
```

Reads leads from the inventory API (`SCRAPER_BASE_URL`); writes cards to
Airtable. Secrets live in `system_b/.env` (gitignored — never commit).
