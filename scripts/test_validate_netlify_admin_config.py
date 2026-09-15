from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate-netlify-admin-config.py"
FIXTURES = ROOT / "scripts" / "fixtures" / "netlify-admin-config"


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_netlify_admin_config",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NetlifyAdminConfigValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator()

    def parse_fixture(self, fixture_name):
        return self.validator.parse_netlify_config(
            (FIXTURES / fixture_name).read_text(encoding="utf-8")
        )

    def test_current_config_accepts_edge_proxy_contract(self):
        build, _headers, edge_functions, redirects = self.validator.parse_netlify_config(
            (ROOT / "netlify.toml").read_text(encoding="utf-8")
        )

        self.validator.validate_edge_api_proxy(build, edge_functions, redirects)

    def test_legacy_api_redirect_conflicts_with_edge_proxy(self):
        build, _headers, edge_functions, redirects = self.parse_fixture(
            "legacy-api-redirect.toml"
        )

        with self.assertRaisesRegex(AssertionError, r"conflicting /api/\* redirect"):
            self.validator.validate_edge_api_proxy(build, edge_functions, redirects)

    def test_missing_api_proxy_edge_route_is_rejected(self):
        build, _headers, edge_functions, redirects = self.parse_fixture(
            "missing-api-proxy-edge-route.toml"
        )

        with self.assertRaisesRegex(AssertionError, r"api-proxy edge function"):
            self.validator.validate_edge_api_proxy(build, edge_functions, redirects)


if __name__ == "__main__":
    unittest.main()
