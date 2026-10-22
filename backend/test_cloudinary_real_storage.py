"""Opt-in destructive test against a dedicated TEST Cloudinary cloud.

Skipped unless ``real_storage_gate`` accepts the configuration (see that module).
Everything happens under one random, high-entropy owner prefix ``listings/<id>/``;
only that prefix is purged. No presets or other cloud settings are touched.

User setup: create ``.env.test.local`` (gitignored) in the repository root with
    UA_TEST_CLOUDINARY_URL=cloudinary://<key>:<secret>@<test_cloud_name>
    UA_TEST_CLOUDINARY_CONFIRM=<test_cloud_name>
then run:  .venv/bin/python -m unittest backend.test_cloudinary_real_storage -v
"""

import importlib
import os
import secrets
import sys
import unittest
from unittest import mock

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import real_storage_gate  # noqa: E402

TEST_URL, SKIP_REASON = real_storage_gate.resolve()
PIXEL = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


@unittest.skipUnless(TEST_URL, SKIP_REASON or "real test storage not configured")
class CloudinaryRealStorageTests(unittest.TestCase):
    def setUp(self):
        import cloudinary
        import cloudinary.api  # noqa: F401
        import cloudinary.uploader  # noqa: F401

        self.cloudinary = cloudinary
        self.env = mock.patch.dict(os.environ, {"CLOUDINARY_URL": TEST_URL})
        self.env.start()
        cloudinary.reset_config()
        cloudinary.config(secure=True)
        # Last line of defence: the SDK must really point at the confirmed test cloud.
        self.assertEqual(cloudinary.config().cloud_name.lower(), real_storage_gate.cloud_name_of(TEST_URL))
        self.media = importlib.import_module("media_routes")
        self.app_module = importlib.import_module("app")
        self.patches = [
            mock.patch.object(self.app_module, "CLOUDINARY_URL", TEST_URL),
            mock.patch.object(self.app_module, "S3_BUCKET", ""),
            mock.patch.object(self.app_module, "S3_ACCESS_KEY", ""),
            mock.patch.object(self.app_module, "S3_SECRET_KEY", ""),
        ]
        [patch.start() for patch in self.patches]
        self.owner = 10**12 + secrets.randbelow(9 * 10**12)
        self.prefix = f"listings/{self.owner}/"

    def tearDown(self):
        try:
            self.media.purge_user_media([], self.owner)  # only this test's prefix
        finally:
            [patch.stop() for patch in self.patches]
            self.env.stop()
            self.cloudinary.reset_config()

    def _upload(self, name):
        public_id = f"{self.prefix}{name}"
        result = self.cloudinary.uploader.upload(PIXEL, public_id=public_id, overwrite=True, resource_type="image")
        return public_id, result["secure_url"]

    def _exists(self, public_id):
        from cloudinary.exceptions import NotFound

        try:
            self.cloudinary.api.resource(public_id)
            return True
        except NotFound:
            return False

    def test_upload_delete_then_late_upload_is_swept(self):
        first_id, first_url = self._upload("a/photo")
        self.assertTrue(self._exists(first_id))
        self.assertEqual(self.media.purge_user_media([first_url], self.owner, heartbeat=lambda: True), [])
        self.assertFalse(self._exists(first_id))
        # A signature issued before the account lock lands after the first purge.
        late_id, _ = self._upload("late/photo")
        self.assertTrue(self._exists(late_id))
        self.assertEqual(self.media.purge_user_media([], self.owner, heartbeat=lambda: True), [])
        self.assertFalse(self._exists(late_id))

    def test_lease_loss_issues_no_provider_deletes(self):
        public_id, url = self._upload("keep/photo")
        self.assertEqual(self.media.purge_user_media([url], self.owner, heartbeat=lambda: False), ["lease-lost"])
        self.assertTrue(self._exists(public_id))


if __name__ == "__main__":
    unittest.main()
