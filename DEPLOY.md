# Deploy — Track H operator service (production go-live)

ONE FastAPI service (`system_b/api/app.py`) serves everything:

- `GET  /health` — unauthenticated health check
- `POST /webhooks/smartlead?token=…` — Smartlead reply webhook (Track B / B5)
- `/api/*` — the operator UI API (bearer auth) + a background timing-guard loop

Runs on **Railway or Render** unchanged (Dockerfile + Procfile both provided).

## 1. Start command (baked in)

- **Dockerfile** (Render auto-detects it; Railway can use it):
  `uvicorn system_b.api.app:app --host 0.0.0.0 --port ${PORT:-8000}`
- **Procfile** (Railway/Heroku-style buildpack):
  `web: uvicorn system_b.api.app:app --host 0.0.0.0 --port $PORT`

Both read `$PORT` from the platform. No other start config needed.

## 2. Environment variables

⚠️ **Use the ROTATED keys** (from the E1 rotation list) for every secret below —
NOT the old multi-tree values. `SMARTLEAD_API_KEY` was single-tree, so it does
not need rotation; `AIRTABLE_TOKEN` and `OPENAI_API_KEY` were multi-tree → use
the freshly-rotated values.

**Secret** (set as secret/encrypted env vars):

| Var | What |
|---|---|
| `AIRTABLE_TOKEN` | Airtable PAT (**rotated**) — CRM read/write |
| `OPENAI_API_KEY` | OpenAI (**rotated**) — research + follow-up descriptions (the generate job runs on the service) |
| `SMARTLEAD_API_KEY` | Smartlead (single-tree, no rotation needed) |
| `UI_AUTH_TOKEN` | bearer secret for `/api/*` (the operator login token) |
| `WEBHOOK_TOKEN` | guards the Smartlead webhook URL |
| `NTFY_TOPIC` | reply-alert push topic — `systemb-alerts-93348444b942` (anyone with it can read/send, so treat as secret) |

**Config** (non-secret):

| Var | Value |
|---|---|
| `AIRTABLE_BASE_ID` | your base id |
| `AIRTABLE_TABLE_NAME` | `Prospects` |
| `SCRAPER_BASE_URL` | `https://www.ishaangpta.com` |
| `SMARTLEAD_CAMPAIGN_IDS` | `cfo:3625994` (the DRAFTED production campaign) |
| `UI_ALLOWED_ORIGINS` | the deployed frontend origin(s), comma-separated (CORS) |
| `WEBHOOK_PUBLIC_URL` | `https://<your-service>/webhooks/smartlead` (used by the register step) |
| `NTFY_SERVER` | `https://ntfy.sh` (default; omit unless self-hosting) |
| `GUARD_INTERVAL_S` | `3600` (default; the timing-guard cadence) |
| `SCHEDULER_ENABLED` | `1` (leave on in prod so the timing guard runs) |

## 3. Register the reply webhook (post-deploy, one-off)

After the service is live, register the webhook against the deployed URL. Run
this once, with the deploy's env available (locally with prod env, or from a
Railway/Render one-off shell):

```
python -m system_b.scripts.register_webhook 3625994
```

It reads `WEBHOOK_PUBLIC_URL` + `WEBHOOK_TOKEN` and registers `EMAIL_REPLY` +
`LEAD_UNSUBSCRIBED` on campaign `3625994`. (It does not start a server.)

## 4. Verify it's live

1. **Health:** `curl https://<your-service>/health` → `{"ok":true}`.
2. **Fire one test reply** (simulates Smartlead's POST — confirms the deployed
   handler → freeze → ntfy chain over the real internet path):
   ```
   curl -X POST "https://<your-service>/webhooks/smartlead?token=<WEBHOOK_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"event_type":"EMAIL_REPLY","to_email":"<an eligible prospect email>",
          "subject":"Re: test","reply_body":"test","time_replied":"2026-07-12T00:00:00Z",
          "campaign_id":3625994}'
   ```
   Expect `{"status":"frozen",...}`, the prospect goes `frozen`/`replied` in
   Airtable, and an **ntfy push** hits your phone. (Use a real prospect's email
   to see it freeze a real row; a made-up email returns `unknown_lead`.)
3. **Real end-to-end** (the actual test you'll run): flip one real prospect
   `eligible_for_send`, approve → real send, reply to it from that inbox →
   Smartlead delivers the webhook to the deployed URL → freeze + ntfy. No curl.

## 5. Go-live sequencing (send-safety)

- The **production campaign `3625994` stays DRAFTED** until you start it.
- **`eligible_for_send` defaults OFF** — approve is refused (`NotEligibleError`)
  for any prospect you haven't explicitly flipped, in the UI or via
  `POST /api/prospects/{id}/eligible?eligible=true`. Send-safety is structural,
  not attention-dependent.
- Plan: start the campaign → flip ONE real prospect eligible → send → reply →
  confirm the real webhook freeze + ntfy → then the first ~10.
