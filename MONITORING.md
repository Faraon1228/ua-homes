# Sentry monitoring runbook

Sentry is the only crash/error provider in this release. Firebase Crashlytics is deliberately deferred. All four surfaces start normally when their DSN is absent; source-map upload also skips when its auth token is absent.

## Sentry projects and external configuration

Create these projects in one Sentry organization (replace `<org-slug>` only with the real organization slug):

| Surface | Sentry project slug | Runtime configuration |
|---|---|---|
| Railway Flask API | `ua-homes-backend` | Railway `SENTRY_DSN`, `SENTRY_ENVIRONMENT=production`, optional `SENTRY_RELEASE`, `SENTRY_TRACES_SAMPLE_RATE=0.01`, `SENTRY_PROFILES_SAMPLE_RATE=0` |
| Netlify public web/PWA | `ua-homes-web` | GitHub secret `SENTRY_WEB_DSN` |
| Netlify staff admin | `ua-homes-admin` | GitHub secret `SENTRY_ADMIN_DSN` |
| UA-Dim Flutter | `ua-dim-flutter` | GitHub secret `UA_DIM_SENTRY_DSN` |

GitHub **Actions variables** required for web symbolication are `SENTRY_ORG=<org-slug>`, `SENTRY_WEB_PROJECT=ua-homes-web`, and `SENTRY_ADMIN_PROJECT=ua-homes-admin`. Optional variables are `SENTRY_WEB_TRACES_SAMPLE_RATE=0.01`, `SENTRY_ADMIN_TRACES_SAMPLE_RATE=0.01`, `UA_DIM_SENTRY_TRACES_SAMPLE_RATE=0.01`, and `UA_DIM_SENTRY_PROFILES_SAMPLE_RATE=0`.

GitHub **Actions secret** `SENTRY_AUTH_TOKEN` is used only by the main-branch web build. Give it organization read and project release/source-map write access for the two web projects. Never put it in Railway, Netlify, a dart-define, a bundle, or a build artifact. The browser DSNs are public ingestion identifiers by design; the pipeline injects them into the final self-hosted SDK bundles. It generates maps only in the deploy job, uploads them to the matching release, deletes every `*.map`, and then packages `web/`.

Netlify uses `--no-build`, so Sentry values must remain in GitHub Actions rather than Netlify build variables. Do not add `SENTRY_AUTH_TOKEN` to Netlify. If the build is ever moved to Netlify, mirror only `UA_HOMES_SENTRY_WEB_DSN`, `UA_HOMES_SENTRY_ADMIN_DSN`, `UA_HOMES_SENTRY_ENVIRONMENT`, and the two trace rates there, and keep source-map upload in a secret build context.

Flutter release jobs pass the DSN, environment, release SHA, traces, and profiles through `--dart-define`. Local/review builds omit the DSN and remain disabled. The SDK's offline envelope cache handles transient connectivity; network, WebView, console, auth, upload, and input breadcrumbs are dropped.

## Privacy and noise policy

The backend and browsers discard expected authentication, authorization, validation, rate-limit and other 4xx failures. Browser/mobile offline and ordinary network failures are discarded. Authorization/CSRF/cookies and password/token/phone/email/message/upload/contact/location fields are removed or replaced before send; users, request bodies, query strings, and backend stack-frame local variables are not sent. Request IDs, safe route templates, environment and release remain for diagnosis. Traces default to 1%; profiling defaults to off.

## Rollout, verification, and rollback

1. Create projects and alert rules, then configure DSNs with trace/profile rates still at their defaults. Deploy through the normal protected pipeline; do not use a public “throw error” route.
2. Confirm `/api/health` reports `monitoring.provider=sentry` and the intended `enabled` state. This endpoint never exposes a DSN.
3. In an authenticated staging/admin session, use browser DevTools to run `window.uaSentryCaptureException(new Error('authorized verification'))`. For Flutter/backend, use an authenticated, temporary internal test path or local test transport—not a public endpoint—and then remove it before release. Confirm environment, release, request ID, stack/source mapping and absence of PII.
4. Check expected 401/403/404/422/429 and offline actions do not create issues. Raise trace rates only after reviewing volume and cost.
5. Roll back independently by clearing the affected DSN and redeploying/restarting. For immediate volume control, set trace/profile rates to `0`. Revoke `SENTRY_AUTH_TOKEN` to stop map upload; runtime error capture continues. Revert the application commit only if SDK code itself is implicated.

## Admin «Стан системи»

The staff dashboard aggregates production service health, new unresolved
Sentry error/fatal issues from the last 24 hours, recent failed deploy runs,
deployed/expected commit SHAs, and notification readiness. Aggregation happens
only in the backend. Sentry, GitHub, email, and Telegram credentials are never
returned to the browser. Issue rows expose only title, culprit, severity,
counts/timestamps, and an allowlisted HTTPS Sentry permalink.

Snapshots are stored in the application database. Read requests never block on
provider calls and mark snapshots older than `UA_HOMES_STATUS_TTL_SECONDS`
(15 minutes by default) as stale. Administrators can force a refresh through
the CSRF-protected UI. The production health workflow
also refreshes the snapshot when `UA_HOMES_STATUS_REFRESH_KEY` exists in both
GitHub Actions and Railway. Provider timeouts are bounded; absent credentials
produce `not_configured`, while provider failures produce `unknown`.

Incident email and optional Telegram messages are transition-based: repeated
degraded/down snapshots are deduplicated, and a recovery notification is sent
when status returns to `ok`. Configure `UA_HOMES_STATUS_ALERT_EMAIL` to enable
email delivery through the existing SendGrid/SMTP sender. No Railway API token
is used or required.
