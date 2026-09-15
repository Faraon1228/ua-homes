from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ApiMigrationPolicyTests(unittest.TestCase):
    def test_runtime_callers_do_not_use_legacy_api_backend_route(self):
        paths = [
            *(ROOT / "backend").rglob("*.py"),
            *(ROOT / "web").glob("*.js"),
            *(ROOT / "web").glob("*.jsx"),
            *(ROOT / ".github" / "workflows").glob("*.yml"),
            *(ROOT / ".github" / "workflows").glob("*.yaml"),
        ]
        offenders = [
            str(path.relative_to(ROOT))
            for path in paths
            if "/api-backend" in path.read_text(encoding="utf-8")
            and path.name != "sw.js"
        ]
        self.assertEqual(offenders, [])

    def test_scheduled_operations_use_public_canonical_api(self):
        for workflow in (
            ROOT / ".github" / "workflows" / "production-health.yml",
            ROOT / ".github" / "workflows" / "database-backup.yml",
        ):
            text = workflow.read_text(encoding="utf-8")
            self.assertIn("API_URL: https://ua-dim.com", text)
            self.assertNotIn("backend-production-51964.up.railway.app", text)

    def test_seo_pages_generate_canonical_relative_api_calls(self):
        text = (ROOT / "backend" / "seo_routes.py").read_text(encoding="utf-8")
        self.assertIn('api_base = ""', text)
        self.assertIn("fetch(`${apiBase}/api/leads`", text)

    def test_client_contract_has_one_prefix_and_no_edge_secret(self):
        public = (ROOT / "web" / "lib" / "apiClient.js").read_text(encoding="utf-8")
        policy = (ROOT / "web" / "lib" / "apiClientPolicy.js").read_text(encoding="utf-8")
        admin = (ROOT / "web" / "admin" / "src" / "lib" / "apiClient.js").read_text(encoding="utf-8")
        self.assertIn('API_PREFIX = "/api"', policy)
        self.assertIn("buildCanonicalApiUrl", public)
        self.assertIn("buildCanonicalApiUrl", admin)
        for text in (public, admin):
            self.assertNotIn("X-UA-Edge-Token", text)
            self.assertNotIn("UA_HOMES_EDGE_TOKEN", text)
        mobile = (ROOT / "apps" / "ua_dim" / "lib" / "services" / "mobile_push_service.dart").read_text(encoding="utf-8")
        self.assertIn("UA_DIM_API_BASE_URL", mobile)
        self.assertIn("'Bearer $authToken'", mobile)


if __name__ == "__main__":
    unittest.main()
