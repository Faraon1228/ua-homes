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
| `UA_HOMES_DB_PATH` | Persistent SQLite path used when `DATABASE_URL` is absent | `backend/ua_homes.db` |
| `UA_HOMES_SEED_DEMO_DATA` | Seed demo users/listings into a fresh PostgreSQL database | `false` |
| `UA_HOMES_REQUIRE_POSTGRES` | Fail startup rather than silently use SQLite | `false` |
| `UA_HOMES_MAINTENANCE_MODE` | Reject mutations with `503`/`Retry-After` during cutover | `false` |

Production must use PostgreSQL. Keep SQLite only for local development and as the
source of the one-time migration:

```bash
# 1. Validate source integrity, target schema, and that PostgreSQL is empty.
python3 backend/migrate_sqlite_to_postgres.py \
  --source /path/to/production.sqlite3 \
  --target "$DATABASE_URL"

# 2. Stop backend writes, take a final SQLite snapshot, then copy and verify rows.
python3 backend/migrate_sqlite_to_postgres.py \
  --source /path/to/final-production.sqlite3 \
  --target "$DATABASE_URL" \
  --execute
```

The migration is transactional, preserves IDs, resets PostgreSQL identity
sequences, refuses non-empty targets, and verifies every table count before
commit. After cutover, set Railway `UA_HOMES_REQUIRE_POSTGRES=true` and the repository variable
`UA_HOMES_DATABASE_ENGINE=postgresql` so the production health workflow enforces
the database engine.

## Backups and production monitoring

| Variable / secret | Location | Description |
|---|---|---|
| `UA_HOMES_BACKUP_TOKEN` | Railway + GitHub Actions | Random bearer token protecting `POST /api/operations/backup` |
| `UA_HOMES_BACKUP_ENCRYPTION_KEY` | GitHub Actions + secure offline copy | Passphrase used to encrypt database backup artifacts |

`Backup production database` runs daily and can be started manually. With the
`UA_HOMES_DATABASE_URL` GitHub secret it creates a PostgreSQL custom-format dump
and restores it into a temporary PostgreSQL service. Until cutover it keeps the
existing SQLite snapshot and integrity-check path. Both paths encrypt the archive
with AES-256-CBC/PBKDF2 and retain only the encrypted artifact for 30 days.

To validate a decrypted snapshot locally:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass env:UA_HOMES_BACKUP_ENCRYPTION_KEY \
  -in ua-homes-backup.tar.gz.enc -out ua-homes-backup.tar.gz
tar -xzf ua-homes-backup.tar.gz
python3 backend/operations_backup.py verify --database backup.sqlite3
python3 backend/operations_backup.py restore-drill --database backup.sqlite3
```

`Monitor production health` runs every 15 minutes against backend readiness,
the public listings API, the seller frontend, and the admin login shell when the
repository variable `UA_HOMES_ADMIN_URL` is configured. It checks three-second
API latency thresholds and optionally enforces `UA_HOMES_DATABASE_ENGINE`. It
opens a single GitHub issue when checks fail and closes that issue after recovery.

## Staff access

The admin site uses the same-origin `/api` proxy. Staff sessions are short-lived
HttpOnly cookies protected by origin and CSRF checks; do not store staff tokens
or operations keys in browser storage. The configured bootstrap credentials
create the first administrator only and never reset an existing account.

Platform roles are `admin` and `moderator`. Administrators manage users,
agencies, requests, system health, and destructive listing operations.
Moderators are limited to dashboard/listing reads, moderation, verification,
listing reports, and audit reads.

## Backend observability

| Variable | Description | Default |
|---|---|---|
| `SENTRY_DSN` | Backend Sentry project DSN; enables Flask errors and traces | disabled |
| `SENTRY_TRACES_SAMPLE_RATE` | Fraction of backend requests recorded as performance traces (`0..1`) | `0.1` |

Every media upload and lead request emits a structured JSON log with request ID,
route, status, database engine, and API duration. All 5xx responses and requests
slower than one second are logged as well. Responses expose `Server-Timing` and
`X-Response-Time-Ms`; `/api/health` reports database engine, storage, distributed
rate-limit, and error-monitoring readiness without exposing credentials.

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

## Frontend observability endpoints

- `POST /api/analytics/client-telemetry` — runtime JS errors and unhandled promise rejections (`event_type`, `message`, optional `payload`).
- `POST /api/analytics/web-vitals` — Core Web Vitals ingestion (`name`, `value`, optional `rating`, `id`, `delta`, `navigation_type`).

## SMS (optional, for phone verification)

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token |
| `TWILIO_FROM_PHONE` | Twilio verified phone number |

In production (when `_production_secret_required()` is true), `POST /api/auth/send-phone-code` returns **503** if Twilio credentials are incomplete or missing, and does **not** store a code. If Twilio is configured but the send fails at runtime, the endpoint returns **502** without persisting a code. The `dev_code` field is only returned in non-production environments when no Twilio provider is configured.

## LiqPay payments

| Variable | Description | Default |
|---|---|---|
| `LIQPAY_MODE` | Explicit payment mode: `disabled`, `sandbox`, or `live` | `disabled` |
| `LIQPAY_PUBLIC_KEY` | LiqPay public key matching the selected mode | none |
| `LIQPAY_PRIVATE_KEY` | LiqPay private signing key matching the selected mode | none |

Payments fail closed. `LIQPAY_MODE=disabled` returns **503** from checkout and does not treat missing keys as a successful demo payment. Sandbox keys are accepted only with `LIQPAY_MODE=sandbox`; `LIQPAY_MODE=live` rejects keys prefixed with `sandbox_` and requires an externally reachable HTTPS `UA_HOMES_PUBLIC_URL`. Set `UA_HOMES_API` to an externally reachable HTTPS backend origin when callbacks do not use the public site's same-origin `/api` proxy.

Checkout requires an authenticated user. Result and callback URLs, amount, currency, description, plan, and order ownership are generated by the backend rather than accepted from the browser. A signed callback activates a plan only when it matches an existing order's mode, amount, currency, user, and plan. `sandbox` status can activate a plan only in explicit sandbox mode; live mode requires `success`. Repeated callbacks are idempotent and do not extend a plan more than once.

Keep `LIQPAY_MODE=disabled` in production until live keys, merchant compliance, refund/support procedures, and an end-to-end live payment test are approved.

## Password reset

Password reset is available via:

- `POST /api/auth/forgot-password` — Accepts `{"email": "..."}`. Rate-limited to 5/hour. Returns a generic 200 regardless of whether the address exists (non-enumerating). In production, returns **503** before claiming delivery if neither SendGrid nor SMTP is configured. A cryptographically random token is generated; only its SHA-256 hash is stored in the database (never the raw value). The reset link keeps the raw token in the URL fragment (`public_app_url()#reset_token=...`) so it is not sent to web-server or CDN logs, and is valid for **30 minutes**.
- `POST /api/auth/reset-password` — Accepts `{"token": "...", "password": "..."}`. Validates the token against its stored hash, checks the 30-minute expiry, enforces a minimum password length of 8 characters, bcrypt-hashes the new password into both `password` and `password_hash` columns, atomically clears the token to prevent replay, invalidates all previously issued JWT sessions, and returns clear 4xx errors without leaking sensitive data.

## Gunicorn tuning (optional)

| Variable | Default | Description |
|---|---|---|
| `GUNICORN_WORKERS` | `4` | Number of worker processes |
| `GUNICORN_THREADS` | `2` | Threads per worker |
| `GUNICORN_BIND` | `0.0.0.0:5050` | Bind address |
| `GUNICORN_TIMEOUT` | `30` | Worker timeout seconds |
| `GUNICORN_LOG_LEVEL` | `info` | Log level |
