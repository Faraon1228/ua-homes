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


if __name__ == "__main__":
    unittest.main()
