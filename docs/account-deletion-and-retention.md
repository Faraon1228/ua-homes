# Account deletion jobs, signed uploads and retention inventory

## Durable account deletion

`POST /api/auth/delete-account` verifies the password, then in one transaction sets `users.status='deleting'`,
unpublishes listings and inserts a row in `account_deletion_jobs` (owner id + progress only, no PII). The job runs
three idempotent stages: `media` (purge files) → `database` (scrub/delete account in one transaction, schedule sweep)
→ `sweep` (purge again after `ACCOUNT_DELETION_SWEEP_DELAY_SECONDS`, default 7200 s, longer than the ~1 h Cloudinary
signature and 15 min S3 URL lifetimes; values below 4200 s are raised to 4200 s).

* API: always `202 deleted:false, pending:true` right after the lock+enqueue. The request never calls external
  storage (no gunicorn/UI timeout risk); the scheduler runs the job. The account stays locked (login/API rejected)
  – no manual unlock. The UI logs the user out.
* Retry: exponential backoff 60 s … 1 h, `MAX_ATTEMPTS=20`, then `status='failed'` with a generic `last_error`
  (`<stage>:<incomplete|not-configured>:<n>`); the account stays locked until an operator fixes storage config and
  runs `UPDATE account_deletion_jobs SET status='pending', attempts=0, next_run_at=<now> WHERE status='failed'`.
* Safety: workers claim a job by compare-and-set lease (30 min, renewed at the start of every stage and before every provider request (heartbeat with real elapsed time; a fenced worker stops issuing storage calls)). Every stage
  write is fenced by the lease token (a worker whose lease expired gets `lease-lost` and writes nothing; the
  database stage row-locks the job before deleting). Unexpected exceptions go through the same backoff/terminal
  policy and are logged. A crashed worker's lease expires and the job resumes. A single provider request must finish
  within the lease (30 min).
* Execution: `.github/workflows/background-jobs.yml` (cron every 10 min, GitHub scheduled workflows are best-effort)
  calls `POST /api/operations/jobs/run` with the existing `UA_HOMES_STATUS_REFRESH_KEY` secret and fails the run if
  a job is terminally failed or the key is missing. There is no in-process timer; a server restart relies on the next scheduler tick.

## Signed-only uploads

Cloudinary uploads are issued only with API key/secret signatures (`authType: "signed"`). Missing credentials give
503 with an explicit message; the purge also fails closed (`storage:not-configured`) when neither Cloudinary nor S3
is configured, because earlier uploads cannot be ruled out (set `UA_HOMES_STORAGE_DISABLED=1` only for deployments
that never had storage); `CLOUDINARY_UPLOAD_PRESET` is ignored. **Operational blocker:** already existing
*unsigned* presets in the Cloudinary console keep working for anyone who knows the preset name. Set every upload
preset to *Signed* (or delete it) in Cloudinary → Settings → Upload; this cannot be done or verified from code.
Objects uploaded by such presets under `listings/<id>/` are removed by the prefix sweep, but other prefixes are not.

## Retention inventory and decision table (proposal – no legal terms decided)

Only the user-approved periods marked **Approved** below are implemented as age-based deletion; no legal period is assumed. Seller: UA-Dim, a service
seller registered in Ukraine that receives payments; accounting retention must be confirmed by the accountant.

| Data | What it holds today | On account deletion | Decision needed (who) |
|---|---|---|---|
| Account, listings, listing images, favorites, alerts, push tokens, reviews | profile, email, phone, content | deleted | – |
| `premium_orders` | order id, plan, amount, currency, status, provider payment id/status, paid/processed dates, entitlement chain; `user_id` | kept, `user_id` set NULL (no name/email stored) | **Accountant:** which records are primary/accounting documents and for how long; whether provider ids are needed. Owner: nothing to choose before that |
| `lead_requests` | name, phone, email, message, session id, requester id, bank/amount/credit inputs, response | rows of the leaver anonymised immediately (name/contact/message/session cleared); leads about the leaver's listings keep only the request, response cleared | **Approved:** rows are deleted (not anonymised) once `created_at` is older than 12 calendar months (UTC). Leads are not accounting documents unless a contract follows (accountant to confirm) |
| `listing_reports` | reason, details, reporter fingerprint/id | reporter anonymised immediately (id/fingerprint/details removed) | **Approved:** `resolved`/`dismissed` reports are deleted 12 calendar months (UTC) after `closed_at`; open (`pending`/`reviewing`) reports are never purged |
| `lead_funnel_events`, `lead_funnel_session_rollups` | event, listing id, price, session id; rollups: session id, source, counts, first-route/submit/last-event times | events linked via the leaver's lead session ids are deleted immediately | **Approved:** deleted after 30 days (UTC) by the scheduled purge |
| `client_observability_events` | message/stack, page URL, session id, user agent, payload | events linked via the leaver's lead session ids are deleted immediately | **Approved:** deleted after 30 days (UTC) by the scheduled purge |
| `admin_audit_log`, `moderation_log` | admin actor id/role, action, request id, changed-field names (no free text) / moderation reason | actor FK set NULL; audit `resource_id` of user edits nulled; `moderation_log` rows of the leaver's listings go with the listings | **Approved:** deleted 12 calendar months (UTC) after `created_at`. Staff-written `reason` text is not guaranteed anonymous, so it is only bounded by this period |
| `account_deletion_log` / `account_deletion_jobs` | counters; owner id, stage, generic error code | no PII | – (job rows could be pruned after completion; owner choice) |
| Backups | encrypted full dumps, 30 days in Actions artifacts | deleted users reappear in restored backups | **Owner:** accept 30-day backup window or shorten; on restore re-apply deletions |

**Scheduled purge.** `backend/data_retention.py` runs on every `POST /api/operations/jobs/run` (same GitHub
Actions scheduler, no extra worker). Reports age from `closed_at`, which the only status writer (admin PATCH) sets when moving to `resolved`/`dismissed` (final states, no reopen); it is stamped only on a non-terminal -> terminal transition, so repeating `resolved`/`dismissed` never moves it; `created_at`/`updated_at` are never used. History closed before the column existed has no real timestamp, so startup migration baselines it to the migration time (clock starts then, nothing is deleted early); a closed row with NULL `closed_at` is never purged. Cutoffs: telemetry `now - 30 days`; leads `now` minus 12 calendar months
(same day/time one year earlier, clamped to month end, e.g. 29 Feb -> 28 Feb), both UTC, strictly `created_at < cutoff`.
Deletion is in batches of 500 (max 20 batches per table per run, remainder next run) using portable SQL on the
existing `created_at` indexes. Errors are logged without row data and returned in the run summary
(`retention.errors`); the workflow fails on them. Rollups age by `last_event_at` (30 days) and are deleted with the raw events at account deletion; daily and per-listing aggregate counters contain no identifiers and are kept (they are not rebuilt from truncated raw data).

**Limits of the guarantees.** Telemetry has no user id: only events whose `session_id` matches one of the
leaver's lead requests are removed at deletion; other anonymous events (including page URL / user agent / payload,
which may incidentally contain personal text) remain until 30 days. Backups keep deleted data for up to 30 days.
`premium_orders`, `admin_audit_log` and `moderation_log` are not purged. **The first deployment of this code will delete
existing rows older than the cutoffs on the first scheduler run.**

## Release, rollback and readiness runbook

**Rollback target.** Roll back only to a build that is *signed-upload compatible* (this PR or later). The
`account_deletion_jobs` table is additive; older code ignores it, but accounts already `deleting` stay locked and
their jobs stop running while an older build is deployed, so after any rollback re-deploy a job-capable build
before the 30-minute lease/backoff windows matter, and check `/api/operations/jobs/run` output.
Never roll back to a pre-signed build once presets are Signed/deleted: it would break all uploads. Never re-enable
an unsigned preset as a rollback aid.

**If signed upload fails after release.** Check `/api/media/presigned-url` returns 503 with the missing-credentials
message (set `CLOUDINARY_URL` or S3 vars in Railway), verify clock skew and the Cloudinary key/secret pair, then
hard-reload old open pages (cached JS uses the old upload path). Do not disable signing.

**Order.** 1) merge and deploy code; 2) verify web and Flutter signed uploads and run the scheduler manually
(`workflow_dispatch` of `background-jobs.yml`, which exists on `main` only after merge); 3) only then switch
presets to Signed/delete and confirm an unsigned upload is rejected; 4) delete a dedicated test account in production
and watch the job through the deferred sweep.

**Scheduler secrets (names only).** `.github/workflows/background-jobs.yml` and `production-health.yml` read GitHub
secrets `UA_HOMES_STATUS_REFRESH_KEY` and `UA_HOMES_EDGE_TOKEN`; the same refresh key must be set in Railway. At
the time of the audit neither name was listed in repository or environment secrets and the Railway CLI login had
expired, so equality of both sides is unverified. Do not generate a new key until both endpoints are accessible.
The secret `RAILLWAY_TOKEN` (double L) is not referenced by any workflow in this repository (nor are
`RAILWAY_PROJECT_ID`/`RAILWAY_SERVICE_ID`); leave it unchanged until its owner confirms what uses it.

**Backups.** `database-backup.yml` produces AES-encrypted artifacts (30 days); decrypting needs
`UA_HOMES_BACKUP_ENCRYPTION_KEY`, which is deliberately not available to agents. Run the documented
`verify`/`restore-drill` (see `backend/ENV_VARS.md`) on a decrypted copy in a protected temp directory, never over
production, and delete the copy afterwards. The drill procedure was exercised on a synthetic database only.

## Opt-in real test storage check

`backend/test_cloudinary_real_storage.py` runs against a dedicated **test** Cloudinary cloud only. Create the gitignored `.env.test.local` in the repository root (`chmod 600`) with:

```
UA_TEST_CLOUDINARY_URL=cloudinary://<key>:<secret>@<test_cloud_name>
UA_TEST_CLOUDINARY_CONFIRM=<test_cloud_name>
```

The gate (`backend/real_storage_gate.py`) fails closed unless both are set, the confirm value equals the cloud name, and that name differs from any `CLOUDINARY_URL` / `CLOUDINARY_CLOUD_NAME` production reference. Absence of a production reference does not prove isolation, so the explicit confirm is always required. Only a random `listings/<id>/` prefix is touched; presets are never changed. Run: `.venv/bin/python -m unittest backend.test_cloudinary_real_storage -v` (skipped without the file).

## Remaining retention categories (not approved, not implemented)

| Category | PII risk | Proposed operational decision (owner to confirm) |
|---|---|---|
| `premium_orders` | no name/email after deletion; provider payment id, amounts, dates link to the payment processor | Keep; **accountant** sets the period for primary accounting records. No automated purge until then |
| `account_deletion_log` / `account_deletion_jobs` | counters / owner id only, no PII | Prune completed jobs after e.g. 90 days (optional, owner) |
| Backups | contain everything for up to 30 days | Accept 30-day window; re-apply deletions after any restore |
