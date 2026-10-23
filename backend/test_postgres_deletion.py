"""Opt-in PostgreSQL integration test for durable account deletion.

Run against a throwaway database only (never production):

    docker run -d --rm --name uadim-pgtest -e POSTGRES_PASSWORD=test \
      -e POSTGRES_DB=uadim_test -p 55432:5432 postgres:16-alpine
    UA_TEST_POSTGRES_URL=postgresql://postgres:test@localhost:55432/uadim_test \
      UA_TEST_REDIS_URL=redis://localhost:56379/0 \
      .venv/bin/python -m unittest backend.test_postgres_deletion
"""

import datetime
import importlib
import os
import sys
import threading
import unittest
from unittest import mock

POSTGRES_URL = os.environ.get("UA_TEST_POSTGRES_URL", "").strip()
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

if POSTGRES_URL:
    os.environ["DATABASE_URL"] = POSTGRES_URL
    os.environ["REDIS_URL"] = os.environ.get("UA_TEST_REDIS_URL", "redis://localhost:56379/0")
    os.environ["UA_HOMES_SECRET"] = "postgres-deletion-test-secret-32-bytes!!"
    app_module = importlib.import_module("app")
    jobs = importlib.import_module("account_deletion_jobs")


class FakeStorage:
    """In-memory stand-in for the storage prefix purge (no real bucket is touched)."""

    def __init__(self):
        self.objects = set()
        self.fail = 0

    def purge(self, urls, owner_id, heartbeat=None):
        if heartbeat is not None and not heartbeat():
            return ["lease-lost"]
        if self.fail:
            self.fail -= 1
            return ["network-error"]
        prefix = f"listings/{owner_id}/"
        self.objects = {key for key in self.objects if not key.startswith(prefix)}
        return []


@unittest.skipUnless(POSTGRES_URL, "UA_TEST_POSTGRES_URL is not set")
class PostgresDeletionTests(unittest.TestCase):
    def setUp(self):
        app_module.limiter.reset()
        self.client = app_module.app.test_client()
        self.storage = FakeStorage()
        with app_module.app.app_context():
            db = app_module.get_db()
            db.execute("DELETE FROM account_deletion_jobs")
            db.execute("DELETE FROM users WHERE email = 'pg-leaver@example.test'")
            db.commit()
            import bcrypt

            hashed = bcrypt.hashpw(b"correct-password", bcrypt.gensalt(rounds=4)).decode()
            cursor = db.execute(
                "INSERT INTO users (name, email, password, password_hash, role, account_type, email_verified)"
                " VALUES ('Leaver', 'pg-leaver@example.test', ?, ?, 'user', 'owner', 1)",
                (hashed, hashed),
            )
            self.user_id = cursor.lastrowid
            db.commit()
        self.token = app_module.make_token(self.user_id, "pg-leaver@example.test")
        self.storage.objects.add(f"listings/{self.user_id}/a/photo.jpg")

    def _delete(self):
        with mock.patch.object(app_module, "purge_user_media", side_effect=self.storage.purge) as purge:
            response = self.client.post(
                "/api/auth/delete-account",
                json={"password": "correct-password", "confirm": True},
                headers={"Authorization": f"Bearer {self.token}"},
            )
        purge.assert_not_called()
        return response

    def _run(self, seconds):
        when = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(seconds=seconds)
        with app_module.app.app_context(), mock.patch.object(
            app_module, "purge_user_media", side_effect=self.storage.purge
        ):
            return jobs.run_due_jobs(app_module.get_db(), app_module, now=when)

    def _scalar(self, sql, *params):
        with app_module.app.app_context():
            return list(app_module.get_db().execute(sql, params).fetchone())[0]

    def test_network_failure_then_resume_then_deferred_sweep(self):
        self.storage.fail = 1
        self.assertEqual(self._delete().status_code, 202)
        self.assertEqual(self._scalar("SELECT status FROM users WHERE id = ?", self.user_id), "deleting")
        self.assertEqual(self._run(5)["outcomes"], {"retry": 1})
        self.assertEqual(self._run(120)["outcomes"], {"progressed": 1})
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM users WHERE id = ?", self.user_id), 0)
        # An upload signed before the lock lands after the database stage.
        self.storage.objects.add(f"listings/{self.user_id}/late/photo.jpg")
        self.assertEqual(self._run(300)["processed"], 0)
        self.assertEqual(self._run(7500)["outcomes"], {"done": 1})
        self.assertFalse(self.storage.objects)

    def test_parallel_workers_claim_each_job_once(self):
        self.assertEqual(self._delete().status_code, 202)
        calls = []
        lock = threading.Lock()

        def counting_purge(urls, owner_id, heartbeat=None):
            with lock:
                calls.append(owner_id)
            return self.storage.purge(urls, owner_id, heartbeat)

        def worker():
            with app_module.app.app_context(), mock.patch.object(
                app_module, "purge_user_media", side_effect=counting_purge
            ):
                when = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(seconds=7300)
                jobs.run_due_jobs(app_module.get_db(), app_module, now=when)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        [thread.start() for thread in threads]
        [thread.join() for thread in threads]
        self.assertEqual(calls, [self.user_id])
        self.assertEqual(self._scalar("SELECT stage FROM account_deletion_jobs WHERE owner_id = ?", self.user_id), "sweep")
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM users WHERE id = ?", self.user_id), 0)

    def test_upload_after_lock_is_rejected(self):
        self.storage.fail = 99
        self.assertEqual(self._delete().status_code, 202)
        response = self.client.post(
            "/api/media/presigned-url",
            json={"filename": "a.jpg", "contentType": "image/jpeg", "size": 10},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(POSTGRES_URL, "UA_TEST_POSTGRES_URL is not set")
class PostgresRetentionTests(unittest.TestCase):
    def test_retention_and_closed_at_on_postgres(self):
        retention = importlib.import_module("data_retention")
        now = datetime.datetime(2026, 10, 22, 12, 0, 0)
        with app_module.app.app_context():
            db = app_module.get_db()
            for table in ("lead_funnel_events", "client_observability_events", "lead_requests",
                          "lead_funnel_session_rollups", "admin_audit_log", "moderation_log"):
                db.execute(f"DELETE FROM {table}")
            db.execute("DELETE FROM listing_reports")
            db.execute("DELETE FROM listings WHERE title = 'retention-pg'")
            owner = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
            if owner is None:
                owner_id = db.execute(
                    "INSERT INTO users (name, email, password, password_hash, role, account_type, email_verified)"
                    " VALUES ('Ret', 'pg-retention@example.test', 'x', 'x', 'user', 'owner', 1)"
                ).lastrowid
            else:
                owner_id = owner["id"]
            listing_id = db.execute(
                "INSERT INTO listings (user_id, title, city, district, price, rooms, area, status)"
                " VALUES (?, 'retention-pg', 'Kyiv', 'Center', 1, 1, 30, 'published')",
                (owner_id,),
            ).lastrowid
            for created in ("2026-09-22 11:59:59", "2026-09-22 12:00:00"):
                db.execute("INSERT INTO lead_funnel_events (event, intent, source, created_at) VALUES ('e','i','s',?)",
                           (created,))
                db.execute("INSERT INTO lead_funnel_session_rollups (session_id, source, last_event_at) VALUES (?, 's', ?)",
                           (f"s-{created}", created))
            for key, status, closed in (
                ("o", "pending", None), ("c-old", "resolved", "2025-10-22 11:59:59"),
                ("c-new", "dismissed", "2025-10-22 12:00:00"), ("c-null", "resolved", None),
            ):
                db.execute(
                    "INSERT INTO listing_reports (listing_id, reporter_fingerprint, reason_code, details, status,"
                    " idempotency_key, closed_at) VALUES (?, 'f', 'spam', 'd', ?, ?, ?)",
                    (listing_id, status, key, closed),
                )
            db.commit()
            result = retention.run_retention(db, app_module, now)
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["deleted"]["lead_funnel_events"], 1)
            self.assertEqual(result["deleted"]["lead_funnel_session_rollups"], 1)
            self.assertEqual(result["deleted"]["listing_reports"], 1)
            left = {r["idempotency_key"] for r in db.execute("SELECT idempotency_key FROM listing_reports").fetchall()}
            self.assertEqual(left, {"o", "c-new", "c-null"})
            self.assertEqual(sum(retention.run_retention(db, app_module, now)["deleted"].values()), 0)
            app_module.init_db()
            baseline = db.execute("SELECT closed_at FROM listing_reports WHERE idempotency_key='c-null'").fetchone()[0]
            self.assertIsNotNone(baseline)
            kept = db.execute("SELECT closed_at FROM listing_reports WHERE idempotency_key='c-new'").fetchone()[0]
            self.assertEqual(kept, "2025-10-22 12:00:00")
            db.execute("DELETE FROM listing_reports")
            db.execute("DELETE FROM listings WHERE title = 'retention-pg'")
            db.commit()
