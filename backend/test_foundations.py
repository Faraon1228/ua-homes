from __future__ import annotations

import datetime
import os
import re
import tempfile
import unittest

from backend.configuration import (
    load_settings,
    production_secret_required,
    resolve_secret,
)
from backend.security_policy import (
    SECURITY_HEADERS,
    build_html_csp,
    cors_origins,
    response_security_headers,
)
from backend.time_helpers import UTC, legacy_timestamp, legacy_utc_now, utc_now


class ConfigurationTests(unittest.TestCase):
    def test_parses_environment_and_preserves_defaults(self):
        with tempfile.TemporaryDirectory() as base_dir:
            defaults = load_settings(base_dir, {})
            self.assertEqual(defaults.db_path, os.path.join(base_dir, "ua_homes.db"))
            self.assertIsNone(defaults.database_url)
            self.assertFalse(defaults.maintenance_mode)
            self.assertEqual(defaults.bootstrap_admin_name, "Admin")

            configured = load_settings(
                base_dir,
                {
                    "UA_HOMES_DB_PATH": " /data/homes.db ",
                    "DATABASE_URL": " postgres://database ",
                    "UA_HOMES_MAINTENANCE_MODE": " YES ",
                    "UA_HOMES_PUBLIC_URL": " https://ua-dim.com/ ",
                    "UA_HOMES_API": " https://api.ua-dim.com/ ",
                    "UA_HOMES_BOOTSTRAP_ADMIN_EMAIL": " ADMIN@EXAMPLE.COM ",
                    "UA_HOMES_BOOTSTRAP_ADMIN_NAME": " ",
                    "REDIS_URL": " redis://cache ",
                },
            )
        self.assertEqual(configured.db_path, "/data/homes.db")
        self.assertEqual(configured.database_url, "postgres://database")
        self.assertTrue(configured.maintenance_mode)
        self.assertEqual(configured.public_site_url, "https://ua-dim.com")
        self.assertEqual(configured.api_origin, "https://api.ua-dim.com")
        self.assertEqual(configured.bootstrap_admin_email, "admin@example.com")
        self.assertEqual(configured.bootstrap_admin_name, "Admin")
        self.assertEqual(configured.redis_url, "redis://cache")

    def test_postgres_requirement_and_production_secret_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "DATABASE_URL must be set"):
            load_settings("/tmp", {"UA_HOMES_REQUIRE_POSTGRES": "true"})

        production_environments = (
            {"RAILWAY_ENVIRONMENT_NAME": "production"},
            {"ENVIRONMENT": "prod"},
        )
        for environment in production_environments:
            with self.subTest(environment=environment):
                self.assertTrue(
                    production_secret_required(None, "", environment)
                )
                with self.assertRaisesRegex(
                    RuntimeError, "UA_HOMES_SECRET must be set"
                ):
                    resolve_secret(None, "", environment)

        self.assertTrue(production_secret_required("postgres://db", "", {}))
        self.assertTrue(
            production_secret_required(None, "https://ua-dim.com", {})
        )
        self.assertFalse(
            production_secret_required(None, "http://localhost:5050", {})
        )
        self.assertEqual(
            resolve_secret(
                "postgres://db",
                "",
                {"UA_HOMES_SECRET": " configured-secret "},
            ),
            "configured-secret",
        )


class SecurityPolicyTests(unittest.TestCase):
    def test_allowed_origins_preserve_defaults_overrides_and_preview_opt_in(self):
        defaults = cors_origins({})
        self.assertIn("https://ua-dim.com", defaults)
        localhost_patterns = [
            origin for origin in defaults if isinstance(origin, re.Pattern)
        ]
        self.assertTrue(
            any(pattern.fullmatch("http://localhost:5173") for pattern in localhost_patterns)
        )

        configured = cors_origins(
            {"UA_HOMES_CORS_ORIGINS": " https://one.test, ,https://two.test "}
        )
        self.assertEqual(configured, ["https://one.test", "https://two.test"])

        preview = cors_origins({"UA_HOMES_ALLOW_NETLIFY_PREVIEW_CORS": "yes"})
        self.assertTrue(
            any(
                isinstance(origin, re.Pattern)
                and origin.fullmatch("https://phase-4.netlify.app")
                for origin in preview
            )
        )

    def test_security_headers_and_csp_contract(self):
        self.assertEqual(SECURITY_HEADERS["X-Frame-Options"], "DENY")
        self.assertEqual(SECURITY_HEADERS["X-Content-Type-Options"], "nosniff")
        self.assertEqual(
            SECURITY_HEADERS["Referrer-Policy"],
            "strict-origin-when-cross-origin",
        )
        http_json_headers = response_security_headers(
            is_secure=False,
            is_html=False,
        )
        self.assertNotIn("Strict-Transport-Security", http_json_headers)
        self.assertNotIn("Content-Security-Policy", http_json_headers)

        https_html_headers = response_security_headers(
            is_secure=True,
            is_html=True,
        )
        self.assertEqual(
            https_html_headers["Strict-Transport-Security"],
            "max-age=31536000; includeSubDomains",
        )
        self.assertIn("Content-Security-Policy", https_html_headers)
        csp = build_html_csp(
            "https://ua-dim.com/catalog",
            "https://api.ua-dim.com",
        )
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn(
            "connect-src 'self' https://api.cloudinary.com "
            "https://res.cloudinary.com https://*.amazonaws.com "
            "https://*.cloudfront.net https://ua-dim.com "
            "https://api.ua-dim.com",
            csp,
        )


class TimeHelperTests(unittest.TestCase):
    def test_utc_helpers_are_aware_with_legacy_serialization_parity(self):
        aware = utc_now()
        self.assertIs(aware.tzinfo, UTC)
        self.assertEqual(aware.utcoffset(), datetime.timedelta(0))
        self.assertIsNone(legacy_utc_now().tzinfo)

        fixture = datetime.datetime(
            2026, 9, 2, 15, 44, 36, 123456, tzinfo=UTC
        )
        expected = fixture.replace(tzinfo=None).isoformat(sep=" ")
        self.assertEqual(legacy_timestamp(fixture), expected)
        self.assertEqual(
            legacy_timestamp(fixture, timespec="seconds"),
            "2026-09-02 15:44:36",
        )


if __name__ == "__main__":
    unittest.main()
