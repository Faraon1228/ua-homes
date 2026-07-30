# UA Homes — Environment Variables

## Required for production

| Variable | Description | Example |
|---|---|---|
| `UA_HOMES_SECRET` | JWT signing secret (min 32 chars) | `openssl rand -hex 32` |
| `UA_HOMES_PUBLIC_URL` | Canonical public URL | `https://ua-dom.com` |

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
| `FROM_EMAIL` | Sender address (default: noreply@ua-dom.com) |
| `SMTP_HOST` | SMTP server host |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASS` | SMTP password |

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
