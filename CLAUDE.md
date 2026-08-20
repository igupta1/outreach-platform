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

Only NEW prospects are processed. `--ledger` records every email ever sequenced,
and the next run drops those people BEFORE it fetches a site or calls a model, so
the review gate always holds exactly the sequences not yet seen and nobody is
reviewed or pasted into the history sheet twice. `--ignore-ledger` re-runs a
fixed list without recording it — necessary while iterating on copy, since a
second run of the same export otherwise produces nothing. `--target N` stops at
N valid sequences so a 200-row export is not paid for in full.

The ledger stores NO status. Who accepted and who replied lives in the
hand-maintained history sheet, so no tool can race the human editing it.

## The review gate exports TWO files

They have different lifetimes. **Download email CSV** goes to the sequencer today
and is never read again — the copy lives in the campaign after that. **Download
LinkedIn CSV** goes into the history sheet and is read WEEKS later, when someone
finally accepts a connection request and you need the message written for them.
`HISTORY_COLUMNS` mirrors the second, so a paste lands exactly under the header.

The card shows only what VARIES per prospect: subject, email 1's head, email 2.
Email 1's closing is dimmed and read-only beneath it (the export re-joins head
and tail into the original body); email 3 and the DMs are byte-identical on every
card and appear once in a collapsed panel at the top. They are authored constants
in code, so read-only is the honest treatment — change them where the reasoning
for each line is written down.

Each card underlines the claims the copy makes ABOUT THE PROSPECT and shows
what backs them on hover: their verbatim words, how we know, and a link to the
page it was found on. `build_review` emits those as `claims` — the exact
substring as it appears in the rendered copy, so the page matches text rather
than tracking offsets, and a claim the copy did not end up making highlights
nothing instead of pointing at the wrong words. Geography is only claimed when
the copy actually opens on it (a niched email names no location, and the city
still appears in the body because a GIFT LEAD is there), each claim underlines
once at its first occurrence, and city/state are marked as coming from Apollo
rather than the prospect's site — the one claim on the card nobody verified.

Email 1 is therefore READ-FIRST: a styled div that swaps to the real textarea on
click and back on blur. The textarea stays in the DOM throughout, so `buildCsv`
keeps reading `.value` and knows nothing about any of it.

`copy/naturalness.py` adds an advisory read of the varying copy: an LLM returns
SPANS that look machine-written and code keeps only spans that appear verbatim,
capped at 3, swallowing every failure. It never writes copy, so the "no model
writes any part of a sent email" rule holds. Kept OUT of `flags` on purpose —
those are stop-signs, these are suggestions, and mixing them teaches the operator
to skim the box that matters. The prompt is tuned to be QUIET (measured: 5 of 30
cards on a live run); if it starts firing on most cards it has stopped being
useful and the prompt, not the threshold, is what to fix.

**The review gate's downloads are the artifact.** `<out>.csv` is written before
review, so it lacks the edits and still contains prospects removed on the gate;
the download is the only file carrying both, and it is what goes to the sequencer
AND into the history sheet. `<out>.review.json` is what the gate reads.

## The finance ladder: three packs, three rungs

`bookkeeping` (junior: bookkeeper, AP/AR, payroll) · `accounting` (controller,
led by a FRACTIONAL controller posting) · `cfo` (fractional CFO). Each is a
different sale to a different buyer, and leadgen keeps the inventories separate
— only 1.7% of companies carry both a junior and a controller-level signal.

**One voice, one line.** Every pack renders the SAME left-field line with only
the audience word swapped (`copy.email.left_field_for`, keyed on `dm_audience`):
"i'm an engineer. built this one for {bookkeepers|accountants|fractional cfos}
after hearing the same thing over and over, referrals dried up and nothing
replaced them." The engineer reveal is what stops a machine-built gift reading
as spray-and-pray, and nothing about it is CFO-specific. What legitimately
differs per pack is the LEADS and the need clause that describes them
("looking for bookkeeping help" / "building out their finance function" /
"showing they need finance help") — not the voice.

**The revenue lever belongs to every pack.** 23% of prospects state a client
revenue range, and the prospects it helps most are the GENERALISTS, whose opener
is otherwise an Apollo merge field. `_revenue_framing` takes the pack's own
`need` clause and both `_framing` (cfo) and `framing_line` (everyone else) route
through it. It was cfo-only once, which also made the review gate's
`_personalization` rank bookkeeping and accounting cards for a lever their copy
never pulled — and that ranking IS the CSV row order.

**No rotation anywhere.** Subject WHATs and the left-field line used to hold
several equivalent phrasings picked by a hash of the firm name. That bought
variety nobody could act on and made the copy harder to reason about, so each
key holds exactly one phrasing. The subject already varies per prospect through
the WHO — their city, their vertical, the lead's role.

**No pack is ever inferred.** The operator hands a list to `--pack` and that
decides the voice; nothing reads a company name. So each pack owns its word
absolutely: `bookkeeping` never says "accountant", `accounting` never says
"bookkeeper". Calling a CPA a bookkeeper reads as not having looked, and the
reverse leaves a bookkeeper feeling the mail was meant for someone else. A test
pins this.

`accounting` and `cfo` do share `job_finance_lead` — neither a
fractional-controller nor a fractional-CFO pool is deep enough to gift from
alone — but each LEADS with its own in-market signal, so the gifts differ even
where the pool is shared. `bookkeeping` has no lead-first signal and cannot get
one: outsourced bookkeeping is not a role a company advertises for.

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
  The FRACTIONAL tier gets `MAX_FRACTIONAL_LEAD_AGE_DAYS` (30) instead, for the
  same reason leadgen scrapes it on a 60-day cycle: that universe is small and a
  part-time CFO search is not backfilled in three weeks. Past
  `MAX_DATED_LEAD_AGE_DAYS` (21) the line carries NO relative date — the
  present-tense claim survives, the freshness claim does not. That trade is what
  makes the wider window honest rather than merely permissive, and it is the
  ONLY lever that grows the fractional pool (47 -> 117 live cfo leads). Loosening
  the evidence gate instead recovers nothing: every wide-list word and every
  engagement phrase was measured against live inventory and every single match
  was a duty or a benefit ("Forms 1099", "40 hours per Week (Full-Time)",
  "oversee outsourced accounting providers", "This is not a purely advisory
  position"). Do not re-loosen it on the theory that there is signal in there.

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
- **The fractional word is earned, not inherited.** leadgen tags a posting
  `job_fractional_cfo` / `job_fractional_controller` off a WIDE list (fractional,
  interim, part-time, outsourced, virtual, contract, temp, consultant,
  consulting, advisory) matched in the title OR anywhere in the body. Most of
  those appear incidentally in ordinary job copy, so the TAG cannot carry the
  claim: measured on live inventory, 31 of 171 cfo and 22 of 40 accounting
  fractional postings matched only a weak word, including plain "Chief Financial
  Officer" titles at a law firm and a medical center. `inventory._fractional_evidence`
  re-derives it from the three never-incidental words and
  `adapt_leadgen_lead` DOWNGRADES an unevidenced tag to `job_finance_lead` —
  once, at the door, so the subject WHAT, the pack's signal rank, the lead-first
  priority pick and the DM all agree without any of them knowing the rule exists.
  Do not restore the raw tag as the source of a "fractional" claim.
- **The printed role comes from `Lead.headline_signal`, never `signals[0]`.** A
  company with several postings carries several signals and `signal_type` names
  the strongest, which is not always the first. Reading `signals[0]` made the
  subject describe one posting and the body another (7 of 848 live cfo leads).
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
