import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import real_storage_gate as gate  # noqa: E402

URL = "cloudinary://key:secret@uadim-test"


class RealStorageGateTests(unittest.TestCase):
    def test_skips_when_not_configured(self):
        self.assertEqual(gate.resolve({}, {})[0], "")

    def test_requires_explicit_matching_confirm(self):
        self.assertIn("not both set", gate.resolve({"UA_TEST_CLOUDINARY_URL": URL}, {})[1])
        env = {"UA_TEST_CLOUDINARY_URL": URL, "UA_TEST_CLOUDINARY_CONFIRM": "other"}
        self.assertIn("does not match", gate.resolve(env, {})[1])

    def test_rejects_malformed_url_and_never_echoes_credentials(self):
        env = {"UA_TEST_CLOUDINARY_URL": "cloudinary://onlyhost", "UA_TEST_CLOUDINARY_CONFIRM": "onlyhost"}
        url, reason = gate.resolve(env, {})
        self.assertEqual(url, "")
        env = {"UA_TEST_CLOUDINARY_URL": URL, "UA_TEST_CLOUDINARY_CONFIRM": "nope"}
        self.assertNotIn("secret", gate.resolve(env, {})[1])

    def test_refuses_production_cloud_by_url_or_name(self):
        base = {"UA_TEST_CLOUDINARY_URL": URL, "UA_TEST_CLOUDINARY_CONFIRM": "uadim-test"}
        self.assertEqual(gate.resolve({**base, "CLOUDINARY_URL": "cloudinary://a:b@uadim-test"}, {})[0], "")
        self.assertEqual(gate.resolve({**base, "CLOUDINARY_CLOUD_NAME": "UADIM-TEST"}, {})[0], "")
        self.assertEqual(gate.resolve({**base, "CLOUDINARY_URL": "cloudinary://a:b@prod"}, {})[0], URL)

    def test_absent_production_reference_still_requires_confirm(self):
        self.assertEqual(gate.resolve({"UA_TEST_CLOUDINARY_URL": URL}, {})[0], "")

    def test_reads_only_allowed_keys_from_named_file_without_evaluating(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as handle:
            handle.write(f"# c\nUA_TEST_CLOUDINARY_URL={URL}\nUA_TEST_CLOUDINARY_CONFIRM='uadim-test'\n"
                         "CLOUDINARY_URL=cloudinary://x:y@z\nEVIL=$(touch /tmp/pwned)\n")
        try:
            values = gate.read_env_file(handle.name)
        finally:
            os.unlink(handle.name)
        self.assertEqual(set(values), set(gate.ALLOWED_KEYS))
        self.assertEqual(gate.resolve({}, values), (URL, ""))


if __name__ == "__main__":
    unittest.main()
