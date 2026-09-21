# UA Homes architecture baseline

**Scope:** repository inventory for current `main` after #67, plus the #69
production-hardening changes. This is evidence-based documentation only; it
does not change runtime or deployment behavior. “Active” means wired by
checked-in application/configuration code. A deployment claim is marked
**unknown** when the repository cannot prove the live provider setting.

## Runtime topology and request flow

The canonical production API path supported by the checked-in configuration is:

```text
Browser / UA-Dim WebView
  -> Netlify-hosted static web/ (ua-dim.com)
  -> Netlify Edge Function /api/* (adds X-UA-Edge-Token)
  -> Railway Flask service /api/*
  -> PostgreSQL/Redis and optional storage, email, Sentry, Firebase providers
```

`netlify.toml` publishes `web/`, maps `/api/*` to
`netlify/edge-functions/api-proxy.ts`, and maps both `/api-backend` and
`/api-backend/*` to `netlify/edge-functions/retired-api-backend.ts`. The API
proxy preserves the path/query, removes hop-by-hop headers, adds
`X-UA-Edge-Token`, and fails closed with `503 edge_not_configured` when its
Netlify secret is absent. The retired backend path returns JSON
`410 legacy_api_backend_retired` and does not call `fetch`, Railway, or any
other origin.

Live verification on 2026-09-21 showed:

| URL | Expected status after #69 deploy | Meaning |
|---|---:|---|
| `https://ua-dim.com/api/listings?limit=1` | successful application response | canonical public API path through Netlify Edge |
| `https://ua-dim.com/api-backend/listings?limit=1` | `410` JSON, `code=legacy_api_backend_retired` | legacy production API path retired and blocked |
| `https://backend-production-51964.up.railway.app/api/listings` | `403` JSON, `code=edge_required` | direct Railway API remains protected |
| `https://backend-production-51964.up.railway.app/api/health` | successful health response | intentional public health exception |

Netlify still contains backend-rendered content rewrites to Railway for
`/seo/*`, `/zhk/*`, `/listing/*`, `/sitemap.xml`, `/agencies*`, and
`/insights*`. Those are not public API prefixes and are separate from the
canonical `/api/*` client contract.

## API bases and callers

#67 consolidated browser/admin/mobile API client policy onto the canonical
`/api/*` contract. New callers must use canonical clients or relative
`/api/*` paths; `/api-backend/*` is reserved only for the explicit retirement
response, validators, docs, and regression fixtures.

| Caller | Base resolution | Evidence |
|---|---|---|
| Public web client | `window.UA_HOMES_API`, otherwise same-origin; local fallback `http://127.0.0.1:5050`; appends exactly one `/api` | `web/lib/apiClient.js`, `web/lib/apiClientPolicy.js`, `API_CLIENT_CONTRACT.md` |
| Staff admin | same-origin `/api/admin` with httpOnly session cookie and CSRF header for mutating requests | `web/admin/src/lib/apiClient.js`, `API_CLIENT_CONTRACT.md` |
| UA-Dim mobile | build-time `UA_DIM_API_BASE_URL`; push registration uses canonical `/api/push/devices` without embedding edge secrets | `apps/ua_dim/lib/services/mobile_push_service.dart`, `apps/ua_dim/README.md` |
| Scheduled operations | `https://ua-dim.com/api/*` via Netlify Edge; direct `DATABASE_URL` is preferred for backups when present | `.github/workflows/production-health.yml`, `.github/workflows/database-backup.yml` |
| Netlify `/api-backend*` | retired `410` Edge Function response; no Railway forwarding | `netlify.toml`, `netlify/edge-functions/retired-api-backend.ts` |
| Cloudflare Worker | checked-in reference implementation for `/api/*`, not active for `ua-dim.com` while the domain is delegated to Netlify DNS | `CLOUDFLARE_ORIGIN_PROTECTION.md`, `cloudflare/ua-dim-api-worker.js` |

Do not treat old documentation examples such as
`ua-homes-production.railway.app` as current production endpoints. The current
production Railway origin in checked-in Netlify/edge configuration is
`backend-production-51964.up.railway.app`.

## Flask startup and active route surface

`backend/app.py` creates the Flask app, loads settings, initializes database,
monitoring and security hooks, then registers these blueprints. Gunicorn starts
`app:app` from `backend/railway.toml`; local execution uses `PORT` (default
5050) and `app.run(host="0.0.0.0", ...)`.

| Blueprint | Active route patterns |
|---|---|
| `auth` (`/api/auth`) | `/register`, `/login`, `/me`, `/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`, `/send-phone-code`, `/verify-phone` |
| `payment` (`/api/payment`) | `/liqpay/create`, `/liqpay/callback`, `/orders/<order_id>`, `/plans` |
| `admin` (`/api/admin`) | `/auth/{register,login,session,logout}`; dashboard/stats; listings CRUD/import/export/history; moderation; users; reports; listing reports; verifications; leads; agencies; developers; audit; system health; CSV exports |
| `listing_bp` | `/api/listings*`, `/api/favorites*`, `/api/alerts*`, `/api/recommendations`, `/api/map/listings`, `/api/analytics/*`, `/api/leads`, `/api/inquiries*`, and listing inquiry/review/trust/report/view/verification/freshness routes |
| `media_bp` | `/api/images/{presigned-url,confirm-upload,abort-upload,optimize}`, `/api/media/{presigned-url,confirm-upload}`, `/api/demo-images/<seed>.svg` |
| `system_bp` | `/api/health`, `/api/operations/backup`, `/api/operations/system-status/refresh` |
| `content_bp` | `/api/agencies`, `/api/agencies/<slug>`, `/api/content`, `/agencies`, `/agencies/<slug>`, `/insights`, `/insights/<slug>` |
| `seo_bp` | `/zhk/<slug>`, `/seo/zhk/<slug>`, `/seo/<city>`, `/seo/<city>/<district>`, `/listing/<id>`, `/sitemap.xml`, `/seo/snippets/top`, `/robots.txt`, `/seo/audit` |

The route list above is derived from the checked-in route decorators; the
source files are authoritative for HTTP methods and endpoint names.

## Ownership and deployment contracts

| Surface | Repository evidence | Ownership status |
|---|---|---|
| Netlify public/admin static site | GitHub Actions builds and deploys `web/` with pinned Netlify CLI on `main`; `netlify.toml` is canonical | **active** |
| Netlify `/api/*` Edge proxy | `netlify.toml`, `netlify/edge-functions/api-proxy.ts`, validators, `NETLIFY_EDGE_PROXY.md` | **active canonical API ingress** |
| Netlify `/api-backend*` retirement | `netlify.toml`, `netlify/edge-functions/retired-api-backend.ts`, validators, policy tests | **retired/blocked after #69 deploy** |
| Railway Flask API | `backend/railway.toml`, `Procfile`, health path `/api/health`, protected direct API behavior | **active origin behind Edge**; live project/account ownership **unknown** |
| Cloudflare API Worker | Worker and validation docs remain checked in, but `ua-dim.com` is delegated to Netlify DNS | **reference-only** unless DNS moves to Cloudflare |
| Cloudflare DNS/WAF | Protection guidance exists in `CLOUDFLARE_ORIGIN_PROTECTION.md` | **unknown/reference-only** for current production |
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
python3 -m unittest scripts/test_api_migration_policy.py scripts/test_validate_netlify_admin_config.py
python3 scripts/validate-netlify-admin-config.py
python3 scripts/validate-deploy-workflow.py
python3 scripts/validate-cloudflare-origin-protection.py
python3 scripts/validate-assetlinks.py
npm ci --ignore-scripts --no-audit --no-fund
npm run test:admin
(cd apps/ua_dim && flutter analyze lib test && flutter test --reporter expanded)
```

Dependency-heavy suites are CI contracts and should not be represented as
passing locally unless run in the current checkout.

## Configuration and secrets inventory

Values are intentionally omitted. The canonical backend catalog is
`backend/ENV_VARS.md`.

| Component | Names/categories present in source or workflow |
|---|---|
| Railway Flask | `UA_HOMES_SECRET`, `UA_HOMES_PUBLIC_URL`, `UA_HOMES_CORS_ORIGINS`, `UA_HOMES_ALLOW_NETLIFY_PREVIEW_CORS`, `UA_HOMES_EDGE_TOKEN`, `DATABASE_URL`, `UA_HOMES_DB_PATH`, `UA_HOMES_SEED_DEMO_DATA`, `UA_HOMES_REQUIRE_POSTGRES`, `UA_HOMES_MAINTENANCE_MODE`, `REDIS_URL`, `UA_HOMES_TRUSTED_PROXY_CIDRS`, `UA_HOMES_MAX_CONTENT_LENGTH`, `S3_*`, `CLOUDINARY_*`, `LIQPAY_*`, `SENDGRID_*`/`SMTP_*`, Firebase service-account, alert/backup/status keys, `SENTRY_*`, and bootstrap admin settings |
| Netlify/GitHub web build | `UA_HOMES_API`, `UA_HOMES_PUBLIC_URL`, browser Sentry DSNs/environment/release/sample rates; `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`, Sentry upload credentials |
| Netlify Edge | `UA_HOMES_EDGE_TOKEN` via Netlify environment; injected only by `api-proxy` |
| Cloudflare Worker | `UA_HOMES_EDGE_TOKEN` via Wrangler secret if the reference worker is ever deployed; never in `wrangler.toml` |
| UA-Dim mobile | Firebase `UA_DIM_FIREBASE_*`, `UA_DIM_SENTRY_*`, and Android/iOS signing secrets; passed as build-time defines only when configured |
| Scheduled GitHub operations | `UA_HOMES_DATABASE_URL`, `UA_HOMES_BACKUP_ENCRYPTION_KEY`, `UA_HOMES_BACKUP_TOKEN`, `UA_HOMES_EDGE_TOKEN`, `UA_HOMES_STATUS_REFRESH_KEY`, provider status credentials, SendGrid/DNS credentials, and workflow variables |

## Source, generated outputs, and app ownership

- **Source:** `web/*.jsx`, `web/admin/src/**`, CSS/HTML templates, backend
  Python modules, `apps/ua_dim/lib/**`, and workflow/configuration files.
- **Generated/checked-in outputs:** `web/real-estate-app.js`,
  `web/seller-app.js`, `web/admin/*` bundles, `web/chunks/*`,
  `web/precache-manifest.js`, and generated CSS/assets. They are rebuilt by
  `scripts/rebuild-frontend.sh`; CI verifies no diff after rebuilding.
- The root Flutter tree (`lib/`, root `android/`, `ios/`, etc.) is documented
  as the separate **DriveCommunity** app, but release lineage and whether it is
  still distributed to users remain **unknown** from repository evidence alone.
- `apps/ua_dim/` is the standalone **UA-Dim** mobile shell that loads the
  canonical web experience. Its native bridge/auth/push code is separate from
  the root app. Store/provider dashboard state remains **unknown**.

## Risks, evidence gaps, and proposed owners

| Item | Risk/evidence gap | Proposed owner/status |
|---|---|---|
| Production API ingress | Canonical API ingress is now Netlify `/api/*`; live behavior still depends on deploying #69 and keeping the Netlify edge secret aligned with Railway | Platform owner — **active** |
| `/api-backend` retirement | Repository policy blocks callers and origin proxying, but production changes only after Netlify deploys #69 | Platform owner — **retired/blocked after deploy** |
| Direct Railway API | Expected to reject non-health `/api/*` with `403 edge_required`; provider dashboard ownership is not proven by the repo | Backend/platform owner — **protected origin, ownership unknown** |
| Cloudflare Worker | Checked-in worker remains useful reference but cannot front `ua-dim.com` while DNS is on Netlify | Platform owner — **reference-only** |
| Railway config | Root `railway.toml` and `backend/railway.toml` both exist and describe different contexts | Backend owner — **unknown**, confirm Railway project root/config source |
| Secrets and provider ownership | Repository names variables but cannot prove which Netlify, Railway, Cloudflare, GitHub, Sentry, Firebase, or storage account owns live values | Platform/operations owner — **unknown** |
| Generated web artifacts | Source and bundles are both tracked; manual edits to bundles can be overwritten | Web owner — **active**, enforce rebuild/CI check |
| Tests | CI commands are explicit, but this inventory does not claim dependency-heavy suites passed locally | QA/release owner — **active**, run CI and record results |
| Flutter lineage | Root Flutter app and `apps/ua_dim` coexist; repository evidence does not fully prove release/distribution lineage | Mobile owner — **unresolved** |

## Evidence index

Primary evidence: `backend/app.py`, `backend/*_routes.py`,
`backend/ENV_VARS.md`, `API_CLIENT_CONTRACT.md`, `netlify.toml`,
`netlify/edge-functions/api-proxy.ts`,
`netlify/edge-functions/retired-api-backend.ts`, `NETLIFY_EDGE_PROXY.md`,
`backend/railway.toml`, `CLOUDFLARE_ORIGIN_PROTECTION.md`,
`cloudflare/wrangler.toml`, `cloudflare/ua-dim-api-worker.js`,
`.github/workflows/*`, `scripts/rebuild-frontend.sh`,
`scripts/validate-*.py`, `README.md`, and `apps/ua_dim/README.md`.
