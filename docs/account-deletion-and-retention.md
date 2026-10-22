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
* Safety: workers claim a job by compare-and-set lease (30 min, renewed at the start of every stage). Every stage
  write is fenced by the lease token (a worker whose lease expired gets `lease-lost` and writes nothing; the
  database stage row-locks the job before deleting). Unexpected exceptions go through the same backoff/terminal
  policy and are logged. A crashed worker's lease expires and the job resumes. One storage purge must finish
  within the lease.
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

## Retention inventory (proposal – no legal terms decided)

| Data | Where | Today on account deletion | Needs decision |
|---|---|---|---|
| Account, listings, media, favorites, alerts, push tokens, reviews | users, listings, … | deleted | – |
| Payment orders (amount, plan, provider ids, dates) | `premium_orders` | kept, `user_id` set NULL | Ukrainian seller: confirm with accountant which records are primary documents and the retention period; drop unneeded provider fields |
| Leads / inquiries | `lead_requests` | requester rows anonymised; no age-based deletion | Max age for leads (proposal: delete or anonymise after a fixed period); needs owner decision |
| Reports | `listing_reports` | reporter anonymised | Max age of resolved reports |
| Funnel / client observability events | `lead_funnel_events`, `client_observability_events` (session id, UA, page URL) | untouched, no expiry | Short technical retention + scheduled purge (proposal) |
| Admin audit / moderation log | `admin_audit_log`, `moderation_log` | actor FK set NULL | Audit retention period |
| Deletion log | `account_deletion_log` | anonymous counters | – |

No scheduled purge for leads/telemetry exists yet; implementing one requires the periods above.
