"""Durable, resumable account-deletion jobs.

A job stores only the numeric owner id (the storage namespace ``listings/<id>/``)
and progress state, never PII. Stages:

  media    -> purge stored files while the account is locked ('deleting')
  database -> one transaction scrubs/deletes the account and schedules the sweep
  sweep    -> after previously issued upload signatures expired, purge again

Workers claim a job with a lease (compare-and-set UPDATE), so parallel runners
never execute the same job concurrently, and every stage is idempotent. A
crashed/restarted server simply leaves an expired lease or a due ``next_run_at``;
the scheduler (``POST /api/operations/jobs/run``) resumes it automatically.
"""

from __future__ import annotations

import datetime
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 20
# Stages are idempotent and fenced by the lease token; the lease is renewed at the
# start of every stage, so one stage must finish within this bound.
LEASE_SECONDS = 1800
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 3600
# Cloudinary signatures live ~1h and S3 presigned URLs 15min; sweep after both.
DEFAULT_SWEEP_DELAY_SECONDS = 7200
# Never sweep earlier than the signature lifetime plus a safety margin, so a late
# signed upload cannot outlive the final sweep.
MIN_SWEEP_DELAY_SECONDS = 4200


def sweep_delay_seconds() -> int:
    try:
        configured = int(os.environ.get("ACCOUNT_DELETION_SWEEP_DELAY_SECONDS", DEFAULT_SWEEP_DELAY_SECONDS))
    except ValueError:
        configured = DEFAULT_SWEEP_DELAY_SECONDS
    return max(MIN_SWEEP_DELAY_SECONDS, configured)


def _ts(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def backoff_seconds(attempts: int) -> int:
    return min(BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)), BACKOFF_MAX_SECONDS)


def enqueue(db, user_id: int, now: datetime.datetime | None = None) -> None:
    """Insert the job (no commit). The unique owner index makes this idempotent."""
    stamp = _ts(now or _now())
    existing = db.execute("SELECT id FROM account_deletion_jobs WHERE owner_id = ?", (user_id,)).fetchone()
    if existing:
        return
    db.execute(
        "INSERT INTO account_deletion_jobs (owner_id, stage, status, attempts, next_run_at, created_at, updated_at)"
        " VALUES (?, 'media', 'pending', 0, ?, ?, ?)",
        (user_id, stamp, stamp, stamp),
    )


def _claim(db, job_id: int, now: datetime.datetime) -> str | None:
    token = uuid.uuid4().hex
    cursor = db.execute(
        "UPDATE account_deletion_jobs SET lease_token = ?, lease_until = ?, attempts = attempts + 1, updated_at = ?"
        " WHERE id = ? AND status = 'pending' AND next_run_at <= ?"
        " AND (lease_until IS NULL OR lease_until <= ?)",
        (
            token,
            _ts(now + datetime.timedelta(seconds=LEASE_SECONDS)),
            _ts(now),
            job_id,
            _ts(now),
            _ts(now),
        ),
    )
    db.commit()
    return token if cursor.rowcount == 1 else None


def _renew(db, job_id: int, token: str, now: datetime.datetime) -> bool:
    """Extend the lease; False means another worker owns the job (fenced out)."""
    cursor = db.execute(
        "UPDATE account_deletion_jobs SET lease_until = ?, updated_at = ?"
        " WHERE id = ? AND lease_token = ? AND status = 'pending'",
        (_ts(now + datetime.timedelta(seconds=LEASE_SECONDS)), _ts(now), job_id, token),
    )
    return cursor.rowcount == 1


def _fail_attempt(db, job_id: int, token: str, code: str, now: datetime.datetime) -> str:
    """Record a failed attempt; a stale token (lease lost) changes nothing."""
    row = db.execute(
        "SELECT attempts FROM account_deletion_jobs WHERE id = ? AND lease_token = ?", (job_id, token)
    ).fetchone()
    if not row:
        db.rollback()
        return "lease-lost"
    attempts = int(row["attempts"])
    terminal = attempts >= MAX_ATTEMPTS
    cursor = db.execute(
        "UPDATE account_deletion_jobs SET status = ?, next_run_at = ?, lease_until = NULL, lease_token = NULL,"
        " last_error = ?, updated_at = ? WHERE id = ? AND lease_token = ?",
        (
            "failed" if terminal else "pending",
            _ts(now + datetime.timedelta(seconds=backoff_seconds(attempts))),
            code[:200],
            _ts(now),
            job_id,
            token,
        ),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return "lease-lost"
    db.commit()
    return "failed" if terminal else "retry"


def _heartbeat(db, job_id: int, token: str, started: datetime.datetime):
    """Lease heartbeat for provider I/O: renews using real elapsed time, False when fenced out."""
    t0 = time.monotonic()

    def beat() -> bool:
        moment = started + datetime.timedelta(seconds=time.monotonic() - t0)
        try:
            alive = _renew(db, job_id, token, moment)
            if alive:
                db.commit()
            else:
                db.rollback()
            return alive
        except Exception:
            db.rollback()
            logger.exception("Account deletion job %s heartbeat failed", job_id)
            return False

    return beat


def _failure_code(stage: str, failures: list[str]) -> str:
    kind = "not-configured" if any("not-configured" in str(item) for item in failures) else "incomplete"
    return f"{stage}:{kind}:{len(failures)}"


def _collect_account_media(db, user_id: int) -> list[str]:
    import json

    urls: list[str] = []
    for row in db.execute("SELECT images, videos FROM listings WHERE user_id = ?", (user_id,)).fetchall():
        for column in ("images", "videos"):
            try:
                urls.extend(str(url) for url in json.loads(row[column] or "[]"))
            except (TypeError, ValueError):
                continue
    urls.extend(
        str(row["image_url"])
        for row in db.execute(
            "SELECT li.image_url FROM listing_images li JOIN listings l ON l.id = li.listing_id WHERE l.user_id = ?",
            (user_id,),
        ).fetchall()
    )
    return list(dict.fromkeys(urls))


def _run_media(db, app_mod, owner_id: int, token: str, job_id: int, now) -> str | None:
    if not _renew(db, job_id, token, now):
        db.rollback()
        return "lease-lost"
    db.commit()
    urls = _collect_account_media(db, owner_id)
    try:
        failures = app_mod.purge_user_media(urls, owner_id, heartbeat=_heartbeat(db, job_id, token, now))
    except Exception:
        failures = ["purge-error"]
    if "lease-lost" in failures:
        return "lease-lost"
    if failures:
        return _failure_code("media", failures)
    cursor = db.execute(
        "UPDATE account_deletion_jobs SET stage = 'database', last_error = NULL, updated_at = ?"
        " WHERE id = ? AND lease_token = ?",
        (_ts(now), job_id, token),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return "lease-lost"
    db.commit()
    return None


def _run_database(db, app_mod, owner_id: int, token: str, job_id: int, now) -> str | None:
    sweep_at = _ts(now + datetime.timedelta(seconds=sweep_delay_seconds()))
    try:
        # Row-locks the job inside this transaction: destructive work only runs
        # while this worker still owns the lease.
        if not _renew(db, job_id, token, now):
            db.rollback()
            return "lease-lost"
        user = db.execute("SELECT email, account_type FROM users WHERE id = ?", (owner_id,)).fetchone()
        if user:
            email = str(user["email"] or "").strip().lower()
            listings_removed = db.execute(
                "SELECT COUNT(*) AS n FROM listings WHERE user_id = ?", (owner_id,)
            ).fetchone()["n"]
            open_reports = db.execute(
                "SELECT COUNT(*) AS n FROM listing_reports r JOIN listings l ON l.id = r.listing_id"
                " WHERE l.user_id = ? AND r.status = 'pending'",
                (owner_id,),
            ).fetchone()["n"]
            db.execute(
                "DELETE FROM alert_delivery_receipts WHERE alert_id IN ("
                "SELECT id FROM listing_alerts WHERE user_id = ? OR LOWER(email) = ?)",
                (owner_id, email),
            )
            db.execute("DELETE FROM listing_alerts WHERE user_id = ? OR LOWER(email) = ?", (owner_id, email))
            db.execute("DELETE FROM push_devices WHERE user_id = ?", (owner_id,))
            db.execute("DELETE FROM user_favorites WHERE user_id = ?", (owner_id,))
            db.execute("DELETE FROM reviews WHERE user_id = ?", (owner_id,))
            db.execute(
                "UPDATE lead_requests SET name = 'Видалений користувач', phone = NULL, email = NULL,"
                " message = NULL, response_message = NULL, session_id = NULL, requester_user_id = NULL"
                " WHERE requester_user_id = ? OR LOWER(email) = ?",
                (owner_id, email),
            )
            db.execute(
                "UPDATE lead_requests SET response_message = NULL WHERE listing_id IN ("
                "SELECT id FROM listings WHERE user_id = ?)",
                (owner_id,),
            )
            db.execute(
                "UPDATE listing_reports SET reporter_user_id = NULL, reporter_fingerprint = 'deleted-account',"
                " details = '[removed]', idempotency_key = 'deleted-' || id"
                " WHERE reporter_user_id = ?",
                (owner_id,),
            )
            db.execute("UPDATE premium_orders SET user_id = NULL WHERE user_id = ?", (owner_id,))
            db.execute(
                "DELETE FROM listing_images WHERE listing_id IN (SELECT id FROM listings WHERE user_id = ?)",
                (owner_id,),
            )
            db.execute("DELETE FROM listings WHERE user_id = ?", (owner_id,))
            db.execute("DELETE FROM users WHERE id = ?", (owner_id,))
            db.execute(
                "INSERT INTO account_deletion_log (account_type, listings_removed, open_reports)"
                " VALUES (?, ?, ?)",
                (user["account_type"] or "owner", int(listings_removed), int(open_reports)),
            )
            app_mod._refresh_listing_city_summary(db)
            app_mod._refresh_user_growth_summary(db)
        cursor = db.execute(
            "UPDATE account_deletion_jobs SET stage = 'sweep', next_run_at = ?, lease_until = NULL,"
            " lease_token = NULL, last_error = NULL, updated_at = ? WHERE id = ? AND lease_token = ?",
            (sweep_at, _ts(now), job_id, token),
        )
        if cursor.rowcount != 1:
            db.rollback()
            return "lease-lost"
        db.commit()
    except Exception:
        db.rollback()
        return "database:error"
    app_mod.cache_delete_prefix("public:listings:")
    app_mod.cache_delete_prefix("admin:reports:")
    return None


def _run_sweep(db, app_mod, owner_id: int, token: str, job_id: int, now) -> str | None:
    if not _renew(db, job_id, token, now):
        db.rollback()
        return "lease-lost"
    db.commit()
    try:
        failures = app_mod.purge_user_media([], owner_id, heartbeat=_heartbeat(db, job_id, token, now))
    except Exception:
        failures = ["purge-error"]
    if "lease-lost" in failures:
        return "lease-lost"
    if failures:
        return _failure_code("sweep", failures)
    cursor = db.execute(
        "UPDATE account_deletion_jobs SET status = 'done', lease_until = NULL, lease_token = NULL,"
        " last_error = NULL, completed_at = ?, updated_at = ? WHERE id = ? AND lease_token = ?",
        (_ts(now), _ts(now), job_id, token),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return "lease-lost"
    db.commit()
    return None


def run_job(db, app_mod, job_id: int, now: datetime.datetime | None = None) -> str:
    """Advance one job as far as it can go now.

    Returns 'skipped' (not due/claimed elsewhere), 'progressed' (waiting for the
    deferred sweep), 'done', 'retry' or 'failed'.
    """
    now = now or _now()
    token = _claim(db, job_id, now)
    if not token:
        return "skipped"
    row = db.execute("SELECT owner_id, stage FROM account_deletion_jobs WHERE id = ?", (job_id,)).fetchone()
    owner_id, stage = int(row["owner_id"]), row["stage"]
    runners = {"media": _run_media, "database": _run_database, "sweep": _run_sweep}
    while True:
        try:
            error = runners[stage](db, app_mod, owner_id, token, job_id, now)
        except Exception:
            db.rollback()
            logger.exception("Account deletion job %s stage %s crashed", job_id, stage)
            error = f"{stage}:unexpected-error"
        if error == "lease-lost":
            logger.warning("Account deletion job %s lost its lease during stage %s", job_id, stage)
            return "lease-lost"
        if error:
            logger.warning("Account deletion job %s stage %s failed: %s", job_id, stage, error)
            return _fail_attempt(db, job_id, token, error, now)
        if stage == "media":
            stage = "database"
            continue
        if stage == "database":
            return "progressed"
        return "done"


def run_due_jobs(db, app_mod, limit: int = 10, now: datetime.datetime | None = None) -> dict:
    injected_clock = now is not None  # tests inject a fixed clock; production reads it per job
    now = now or _now()
    stamp = _ts(now)
    due = db.execute(
        "SELECT id FROM account_deletion_jobs WHERE status = 'pending' AND next_run_at <= ?"
        " AND (lease_until IS NULL OR lease_until <= ?) ORDER BY next_run_at, id LIMIT ?",
        (stamp, stamp, int(limit)),
    ).fetchall()
    outcomes: dict[str, int] = {}
    for row in due:
        try:
            outcome = run_job(db, app_mod, int(row["id"]), now if injected_clock else _now())
        except Exception:
            # run_job fences and records stage errors itself; this only covers claim/bookkeeping failures.
            db.rollback()
            logger.exception("Account deletion job %s bookkeeping failed", row["id"])
            outcome = "error"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    counts = {
        item["status"]: int(item["n"])
        for item in db.execute("SELECT status, COUNT(*) AS n FROM account_deletion_jobs GROUP BY status").fetchall()
    }
    return {
        "processed": len(due),
        "outcomes": outcomes,
        "pending": counts.get("pending", 0),
        "failed": counts.get("failed", 0),
    }
