"""Opt-in: network failure + process-death recovery of a deletion job on the TEST cloud.

Gated by real_storage_gate (see test_cloudinary_real_storage). Uses an isolated temp
SQLite DB and one random owner prefix. What is real vs injected:
  * real: Cloudinary uploads/deletes/listing, separate OS processes, a process that
    exits abruptly (os._exit(137)) after the provider delete but before the job
    records progress, DB state persisted across processes.
  * injected: the network failure (ConnectionError raised at the SDK call) and the
    clock (run_due_jobs(now=...)), so no real waiting for lease/backoff/sweep delay.
"""

import importlib
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import real_storage_gate  # noqa: E402

TEST_URL, SKIP_REASON = real_storage_gate.resolve()


@unittest.skipUnless(TEST_URL, SKIP_REASON or "real test storage not configured")
class RealDeletionRecoveryTests(unittest.TestCase):
    def setUp(self):
        import cloudinary
        import cloudinary.api  # noqa: F401
        import cloudinary.uploader  # noqa: F401

        self.tmp = tempfile.TemporaryDirectory()
        self.owner = 10**12 + secrets.randbelow(9 * 10**12)
        self.prefix = f"listings/{self.owner}/"
        self.env = {
            **os.environ,
            "UA_HOMES_DB_PATH": os.path.join(self.tmp.name, "recovery.db"),
            "CLOUDINARY_URL": TEST_URL,
            "RECOVERY_OWNER_ID": str(self.owner),
        }
        for key in ("DATABASE_URL", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
            self.env.pop(key, None)
        os.environ["CLOUDINARY_URL"] = TEST_URL
        cloudinary.reset_config()
        cloudinary.config(secure=True)
        self.cloudinary = cloudinary
        self.assertEqual(cloudinary.config().cloud_name.lower(), real_storage_gate.cloud_name_of(TEST_URL))

    def tearDown(self):
        try:
            self.media = importlib.import_module("media_routes")
            self.media.purge_user_media([], self.owner)
            self.assertEqual(self._remaining(), 0, "test prefix must be empty after cleanup")
        finally:
            self.tmp.cleanup()
            self.cloudinary.reset_config()
            os.environ.pop("CLOUDINARY_URL", None)

    def _remaining(self):
        total = 0
        for resource_type in ("image", "video", "raw"):
            result = self.cloudinary.api.resources(
                type="upload", prefix=self.prefix, resource_type=resource_type, max_results=10
            )
            total += len(result.get("resources", []))
        return total

    def _phase(self, phase):
        done = subprocess.run(
            [sys.executable, os.path.join(BACKEND_DIR, "real_recovery_worker.py"), phase],
            env=self.env, capture_output=True, text=True, timeout=240,
        )
        return done.returncode, done.stdout

    def _job(self):
        with sqlite3.connect(self.env["UA_HOMES_DB_PATH"]) as db:
            return db.execute("SELECT stage, attempts, status FROM account_deletion_jobs").fetchone(), \
                db.execute("SELECT COUNT(*) FROM users WHERE id = ?", (self.owner,)).fetchone()[0]

    def test_network_failure_then_process_death_then_recovery(self):
        code, out = self._phase("lock")
        self.assertEqual(code, 0)
        self.assertIn("delete-status 202", out)
        self.assertEqual(self._remaining(), 2)

        code, out = self._phase("fail")  # injected network error: nothing deleted, job retries
        self.assertEqual(code, 0)
        self.assertIn("'retry': 1", out)
        self.assertEqual(self._remaining(), 2)

        code, _ = self._phase("crash")  # real process death after the real delete
        self.assertEqual(code, 137)
        self.assertEqual(self._remaining(), 0)
        (stage, _attempts, status), user_rows = self._job()
        self.assertEqual((stage, user_rows), ("media", 1))  # still locked, not finished

        late = f"{self.prefix}late/photo"  # upload signed before the lock lands afterwards
        self.cloudinary.uploader.upload(
            "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
            public_id=late, overwrite=True, resource_type="image",
        )
        self.assertEqual(self._remaining(), 1)

        code, out = self._phase("recover")  # fresh process reclaims after lease expiry, no manual reset
        self.assertEqual(code, 0, out)
        self.assertIn("'done': 1", out)
        (stage, _attempts, status), user_rows = self._job()
        self.assertEqual(user_rows, 0)
        self.assertEqual(self._remaining(), 0)  # deferred sweep removed the late upload


if __name__ == "__main__":
    unittest.main()
