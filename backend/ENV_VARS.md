# UA Homes — Environment Variables

## Required for production

| Variable | Description | Example |
|---|---|---|
| `UA_HOMES_SECRET` | JWT signing secret (min 32 chars) | `openssl rand -hex 32` |
| `UA_HOMES_PUBLIC_URL` | Canonical public URL | `https://ua-dim.com` |
| `UA_HOMES_CORS_ORIGINS` | Comma-separated allowed browser origins | `https://ua-dim.com,https://www.ua-dim.com,https://ua-dom.com,https://ua-homes.netlify.app` |
| `UA_HOMES_ALLOW_NETLIFY_PREVIEW_CORS` | Allow `*.netlify.app` preview origins when true (`1/true/yes`) | `false` |

## Database

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL DSN | SQLite (local dev) |

## Rate limiting

| Variable | Description | Default |
|---|---|---|
| `REDIS_URL` | Redis DSN for rate limiter | in-memory (dev only) |

## Email (at least one required for email verification)

| Variable | Description |
|---|---|
| `SENDGRID_API_KEY` | SendGrid API key |
| `FROM_EMAIL` | Sender address (default: noreply@ua-dim.com) |
| `SMTP_HOST` | SMTP server host |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASS` | SMTP password |

Production email verification now returns a clear 503 if neither SendGrid nor SMTP is configured, so the live site will not silently pretend messages were sent.

Saved alerts delivery uses the same email provider settings (`SENDGRID_API_KEY` or SMTP vars).

## Saved alerts delivery / dispatch (optional but recommended)

| Variable | Description |
|---|---|
| `UA_HOMES_ALERTS_DISPATCH_KEY` | Shared secret for `POST /api/alerts/dispatch` (header: `X-Alerts-Dispatch-Key`) |
| `UA_HOMES_ALERTS_PUSH_WEBHOOK_URL` | Webhook URL for push delivery payloads (`saved_alert_match`) |
| `UA_HOMES_ALERTS_PUSH_WEBHOOK_BEARER` | Optional bearer token for push webhook authorization |

Dispatch endpoints:
- `POST/GET /api/alerts/dispatch` — run matching + delivery (`listing_id`, `dry_run`, `trigger` supported).
- `GET /api/alerts/dispatch/health` — last run, 24h summary, recent history, stale flag.

Auth for both endpoints:
- `X-Alerts-Dispatch-Key: <UA_HOMES_ALERTS_DISPATCH_KEY>` **or** admin bearer token.

## SMS (optional, for phone verification)

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_FROM_PHONE` | Twilio verified phone number |

## Gunicorn tuning (optional)

| Variable | Default | Description |
|---|---|---|
| `GUNICORN_WORKERS` | `4` | Number of worker processes |
| `GUNICORN_THREADS` | `2` | Threads per worker |
| `GUNICORN_BIND` | `0.0.0.0:5050` | Bind address |
| `GUNICORN_TIMEOUT` | `30` | Worker timeout seconds |
| `GUNICORN_LOG_LEVEL` | `info` | Log level |
