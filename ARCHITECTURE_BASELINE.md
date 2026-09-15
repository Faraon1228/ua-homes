# UA Homes architecture baseline

**Scope:** repository inventory at `main` (2026-09-15). This is evidence-based
documentation only; it does not change runtime or deployment behavior. “Active”
means wired by checked-in application/configuration code. A deployment claim is
marked **unknown** when the repository cannot prove the live provider setting.

## Runtime topology and request flow

The canonical production path supported by the checked-in configuration is:

```text
Browser / UA-Dim WebView
  -> Netlify-hosted static web/ (ua-dim.com)
  -> Netlify Edge Function /api/* (adds X-UA-Edge-Token)
  -> Railway Flask service
  -> PostgreSQL/Redis and optional storage, email, Sentry, Firebase providers
```

`netlify.toml` publishes `web/`, maps `/api/*` to
`netlify/edge-functions/api-proxy.ts`, and maps `/api-backend/*` directly to
`https://backend-production-51964.up.railway.app/:splat`. The same Railway
origin is hard-coded for `/seo/*`, `/zhk/*`, `/listing/*`, `/sitemap.xml`,
`/agencies*`, and `/insights*`. The edge function preserves the path/query,
removes hop-by-hop headers, adds `X-UA-Edge-Token`, and fails closed with 503
when its Netlify secret is absent.

The backend accepts public `/api/health` without the edge token and protects
other `/api/*` requests according to `backend/app.py` and
`CLOUDFLARE_ORIGIN_PROTECTION.md`. Direct Railway URLs are therefore both a
health-check surface and an intentional diagnostic/legacy bypass surface; they
are not the canonical browser request path.

### API bases and callers

| Caller | Base resolution | Evidence |
|---|---|---|
| Public web client | `window.UA_HOMES_API`, otherwise same-origin; local fallback `http://127.0.0.1:5050`; appends `/api` | `web/lib/apiClient.js`, `web/features/TrustDialog.jsx`, `scripts/build-real-estate-demo.py` |
| Seller/marketplace flows | Same `UA_HOMES_API` convention; direct fetch callers exist in the generated/source marketplace and premium modules | `web/marketplace-extensions.js`, `web/premium.js` |
| Staff admin | Same-origin `/api/admin` with cookie + CSRF | `web/admin/src/lib/apiClient.js` |
| UA-Dim mobile | `https://ua-dim.com/api/push/devices` for push registration; WebView loads `https://ua-dim.com/app...` | `apps/ua_dim/lib/services/mobile_push_service.dart`, `apps/ua_dim/README.md` |
| Netlify `/api-backend/*` | Direct Railway rewrite, not the edge function | `netlify.toml` |
| Monitoring/operations | Direct Railway `https://backend-production-51964.up.railway.app/api/...` | `.github/workflows/production-health.yml` |
| Cloudflare Worker (checked-in) | Same direct Railway origin; forwards `/api/*` with the edge token | `cloudflare/ua-dim-api-worker.js` |

No repository evidence proves that all historical `UA_HOMES_API` build values
point to the current Railway origin. Do not treat old documentation examples
such as `ua-homes-production.railway.app` as current production endpoints.

## Flask startup and active route surface

`backend/app.py` creates the Flask app, loads settings, initializes database,
monitoring and security hooks, then registers these blueprints. Gunicorn starts
`app:app` from `backend/railway.toml`; local execution uses `PORT` (default
5050) and `app.run(host="0.0.0.0", ...)`.

| Blueprint | Active route patterns |
|---|---|
| `auth` (`/api/auth`) | `/register`, `/login`, `/me`, `/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`, `/send-phone-code`, `/verify-phone` |
| `payment` (`/api/payment`) | `/liqpay/create`, `/liqpay/callback`, `/orders/<order_id>`, `/plans` |
| `admin` (`/api/admin`) | `/auth/{register,login,session,logout}`; `/dashboard/{overview,stats}`; `/listings` and `/listings/<id>` plus duplicate/publish/import/export/history; `/moderation/{queue,logs}` and moderation actions; `/users`; `/reports/*`; `/listing-reports*`; `/verifications*`; `/leads*`; `/agencies*`; `/developers*`; `/audit`; `/system/health*`; `/reports/{listings-by-city,user-growth,observability,lead-funnel}` and `/reports/lead-funnel/export.csv` |
| `listing_bp` | `/api/listings*`, `/api/favorites*`, `/api/alerts*`, `/api/recommendations`, `/api/map/listings`, `/api/analytics/{summary,lead-funnel,client-telemetry,web-vitals}`, `/api/leads`, `/api/inquiries*`, and listing inquiry/review/trust/report/view/verification/freshness routes |
| `media_bp` | `/api/images/{presigned-url,confirm-upload,abort-upload,optimize}`, `/api/media/{presigned-url,confirm-upload}`, `/api/demo-images/<seed>.svg` |
| `system_bp` | `/api/health`, `/api/operations/backup`, `/api/operations/system-status/refresh` |
| `content_bp` | `/api/agencies`, `/api/agencies/<slug>`, `/api/content`, `/agencies`, `/agencies/<slug>`, `/insights`, `/insights/<slug>` |
| `seo_bp` | `/zhk/<slug>`, `/seo/zhk/<slug>`, `/seo/<city>`, `/seo/<city>/<district>`, `/listing/<id>`, `/sitemap.xml`, `/seo/snippets/top`, `/robots.txt`, `/seo/audit` |

The route list above is derived from the checked-in `@...route` decorators;
the source files are authoritative for HTTP methods and endpoint names.

## Ownership and deployment contracts

| Surface | Repository evidence | Ownership status |
|---|---|---|
| Netlify public/admin static site | GitHub Actions builds and deploys `web/` with pinned Netlify CLI on `main`; `netlify.toml` is canonical | **active** |
| Railway Flask API | `backend/railway.toml`, `Procfile`, health path `/api/health`, and direct Railway references | **active** for the intended API; live project/account ownership **unknown** |
| Cloudflare API Worker | `cloudflare/wrangler.toml` and worker are validated, but `netlify.toml` states ua-dim.com DNS is delegated to Netlify and Netlify Edge is authoritative | **legacy/unknown live status**; do not infer it fronts production |
| Cloudflare DNS/WAF | Protection guidance exists in `CLOUDFLARE_ORIGIN_PROTECTION.md` | **unknown**; provider dashboard evidence is absent |
| GitHub Actions | CI, deployment, health, backup, DNS, and mobile workflows are checked in | **active** |

## CI, validators, tests, and exact checks

Active workflows are `.github/workflows/{quality-gates,deploy,production-health,
database-backup,configure-sendgrid-dns,mobile-build,ua-dim-ios-store-build}.yml`.
Quality gates compile and test Flask, rebuild/verify frontend artifacts, run
deployment validators and Playwright admin tests, and analyze/test `apps/ua_dim`.
Deployment validates then deploys only on `main`; health runs every 15 minutes
and can open/close an incident issue.

Relevant local commands (from repository root):

```bash
python3 -m py_compile backend/app.py backend/auth_routes.py backend/payment_routes.py backend/media_routes.py backend/system_routes.py backend/content_routes.py backend/seo_routes.py backend/listing_routes.py backend/admin_routes.py backend/configuration.py backend/monitoring.py backend/security_policy.py backend/time_helpers.py backend/migrate_sqlite_to_postgres.py backend/test_trust_features.py backend/test_admin_panel.py backend/test_foundations.py backend/test_monitoring.py
python3 -m unittest backend.test_trust_features backend.test_admin_panel backend.test_foundations backend.test_monitoring
python3 scripts/validate-netlify-admin-config.py
python3 scripts/validate-deploy-workflow.py
python3 scripts/validate-cloudflare-origin-protection.py
python3 scripts/validate-assetlinks.py
npm ci --ignore-scripts --no-audit --no-fund
npm run test:admin
(cd apps/ua_dim && flutter analyze lib test && flutter test --reporter expanded)
```

The first, validator, and TOML syntax checks were run for this baseline.
Dependency-heavy suites are listed as CI contracts and were not represented
as passing unless run in this checkout.

## Configuration and secrets inventory

Values are intentionally omitted. The canonical backend catalog is
`backend/ENV_VARS.md`.

| Component | Names/categories present in source or workflow |
|---|---|
| Railway Flask | `UA_HOMES_SECRET`, `UA_HOMES_PUBLIC_URL`, `UA_HOMES_CORS_ORIGINS`, `UA_HOMES_ALLOW_NETLIFY_PREVIEW_CORS`, `UA_HOMES_EDGE_TOKEN`, `DATABASE_URL`, `UA_HOMES_DB_PATH`, `UA_HOMES_SEED_DEMO_DATA`, `UA_HOMES_REQUIRE_POSTGRES`, `UA_HOMES_MAINTENANCE_MODE`, `REDIS_URL`, `UA_HOMES_TRUSTED_PROXY_CIDRS`, `UA_HOMES_MAX_CONTENT_LENGTH`, `S3_*`, `CLOUDINARY_*`, `LIQPAY_*`, `SENDGRID_*`/`SMTP_*`, `UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64`, alert/backup/status keys, `SENTRY_*`, and bootstrap admin settings |
| Netlify/GitHub web build | `UA_HOMES_API`, `UA_HOMES_PUBLIC_URL`, browser Sentry DSNs/environment/release/sample rates; `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`, Sentry upload credentials |
| Netlify Edge | `UA_HOMES_EDGE_TOKEN` via Netlify environment |
| Cloudflare Worker | `UA_HOMES_EDGE_TOKEN` via Wrangler secret; never in `wrangler.toml` |
| UA-Dim mobile | Firebase `UA_DIM_FIREBASE_*`, `UA_DIM_SENTRY_*`, and Android/iOS signing secrets; passed as build-time defines only when configured |
| Scheduled GitHub operations | `UA_HOMES_DATABASE_URL`, `UA_HOMES_BACKUP_ENCRYPTION_KEY`, `UA_HOMES_STATUS_REFRESH_KEY`, provider status credentials, SendGrid/DNS credentials, and workflow variables |

## Source, generated outputs, and app ownership

- **Source:** `web/*.jsx`, `web/admin/src/**`, CSS/HTML templates, backend
  Python modules, `apps/ua_dim/lib/**`, and workflow/configuration files.
- **Generated/checked-in outputs:** `web/real-estate-app.js`,
  `web/seller-app.js`, `web/admin/*` bundles, `web/chunks/*`,
  `web/precache-manifest.js`, and generated CSS/assets. They are rebuilt by
  `scripts/rebuild-frontend.sh`; CI verifies no diff after rebuilding.
- The root Flutter tree (`lib/`, root `android/`, `ios/`, etc.) is confirmed
  by README/workflow as the separate **DriveCommunity** app.
- `apps/ua_dim/` is confirmed as the standalone **UA-Dim** mobile shell that
  loads the canonical web experience. Its native bridge/auth/push code is
  separate from the root app.
- Whether either Flutter app is still released to users outside the checked-in
  workflows is **unknown**; store/provider dashboards are not in this repo.

## Risks, evidence gaps, and proposed owners

| Item | Risk/evidence gap | Proposed owner/status |
|---|---|---|
| Production API origin | Multiple historical URLs and direct Railway references can drift from `UA_HOMES_API` | Web/platform owner — **active follow-up** |
| `/api` proxy authority | Netlify Edge and Cloudflare Worker contracts both exist; live Cloudflare routing is not proven | Platform owner — Netlify **active**, Cloudflare **legacy/unknown** |
| `/api-backend` | Direct Railway rewrite bypasses the canonical edge token path | Backend/platform owner — **legacy/active compatibility**, confirm intended callers |
| Railway config | Root `railway.toml` and `backend/railway.toml` both exist and describe different contexts | Backend owner — **unknown**, confirm Railway project root/config source |
| Secrets and provider ownership | Repository names variables but cannot prove which Netlify, Railway, Cloudflare, GitHub, Sentry, Firebase, or storage account owns live values | Platform/operations owner — **unknown** |
| Generated web artifacts | Source and bundles are both tracked; manual edits to bundles can be overwritten | Web owner — **active**, enforce rebuild/CI check |
| Tests | CI commands are explicit, but this inventory does not claim dependency-heavy suites passed locally | QA/release owner — **active**, run CI and record results |
| Mobile release state | App source/workflows exist, but store and signing dashboard state is unavailable | Mobile owner — **unknown** |

## Evidence index

Primary evidence: `backend/app.py`, `backend/*_routes.py`,
`backend/ENV_VARS.md`, `netlify.toml`, `netlify/edge-functions/api-proxy.ts`,
`backend/railway.toml`, `cloudflare/wrangler.toml`,
`cloudflare/ua-dim-api-worker.js`, `.github/workflows/*`,
`scripts/rebuild-frontend.sh`, `scripts/validate-*.py`,
`README.md`, and `apps/ua_dim/README.md`.
