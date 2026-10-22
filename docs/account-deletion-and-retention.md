# Account deletion jobs, signed uploads and retention inventory

## Durable account deletion

`POST /api/auth/delete-account` verifies the password, then in one transaction sets `users.status='deleting'`,
unpublishes listings and inserts a row in `account_deletion_jobs` (owner id + progress only, no PII). The job runs
three idempotent stages: `media` (purge files) → `database` (scrub/delete account in one transaction, schedule sweep)
→ `sweep` (purge again after `ACCOUNT_DELETION_SWEEP_DELAY_SECONDS`, default 7200 s, longer than the ~1 h Cloudinary
signature and 15 min S3 URL lifetimes).

* API: `200 deleted:true, media_cleanup_pending:true` when the account is gone but the sweep is pending;
  `202 deleted:false, pending:true` when media cleanup failed and the job will retry. The account stays locked
  (login/API rejected) – no manual unlock. The UI logs the user out in both cases.
* Retry: exponential backoff 60 s … 1 h, `MAX_ATTEMPTS=20`, then `status='failed'` with a generic `last_error`
  (`<stage>:<incomplete|not-configured>:<n>`); the account stays locked until an operator fixes storage config and
  runs `UPDATE account_deletion_jobs SET status='pending', attempts=0, next_run_at=<now> WHERE status='failed'`.
* Safety: workers claim a job by compare-and-set lease (10 min), so parallel runners / duplicate cron runs never
  execute one job twice; a crashed worker's lease expires and the job resumes.
* Execution: `.github/workflows/background-jobs.yml` (cron every 10 min, GitHub scheduled workflows are best-effort)
  calls `POST /api/operations/jobs/run` with the existing `UA_HOMES_STATUS_REFRESH_KEY` secret and fails the run if
  a job is terminally failed or the key is missing. The request path also runs the job once inline. There is no
  in-process timer; a server restart relies on the next scheduler tick.

## Signed-only uploads

Cloudinary uploads are issued only with API key/secret signatures (`authType: "signed"`). Missing credentials give
503 with an explicit message; `CLOUDINARY_UPLOAD_PRESET` is ignored. **Operational blocker:** already existing
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
