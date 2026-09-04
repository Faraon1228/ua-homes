from __future__ import annotations

import datetime
import os
import re
import runpy
import tempfile
import unittest

from backend.client_identity import parse_trusted_proxy_cidrs, resolve_client_ip
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
        self.assertEqual(configured.max_content_length, 12 * 1024 * 1024)

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

    def test_production_requires_redis_but_development_does_not(self):
        production_environments = (
            {"RAILWAY_ENVIRONMENT_NAME": "production"},
            {"DATABASE_URL": "postgres://database"},
            {"UA_HOMES_PUBLIC_URL": "https://ua-dim.com"},
        )
        for environment in production_environments:
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(RuntimeError, "REDIS_URL must be set"):
                    load_settings("/tmp", environment)
        settings = load_settings("/tmp", {"FLASK_ENV": "development"})
        self.assertIsNone(settings.redis_url)
        local_site_settings = load_settings(
            "/tmp", {"UA_HOMES_PUBLIC_URL": "http://localhost:5050"}
        )
        self.assertIsNone(local_site_settings.redis_url)

    def test_rejects_unsafe_request_size_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "must be at least"):
            load_settings("/tmp", {"UA_HOMES_MAX_CONTENT_LENGTH": "1024"})


class ClientIdentityTests(unittest.TestCase):
    def test_separates_clients_behind_trusted_proxy_chain(self):
        trusted = parse_trusted_proxy_cidrs("10.0.0.0/8, 192.0.2.0/24")
        self.assertEqual(
            resolve_client_ip(
                "10.2.3.4",
                "198.51.100.10, 192.0.2.8",
                trusted,
            ),
            "198.51.100.10",
        )
        self.assertEqual(
            resolve_client_ip(
                "10.2.3.4",
                "198.51.100.11, 192.0.2.8",
                trusted,
            ),
            "198.51.100.11",
        )

    def test_ignores_spoofed_or_malformed_forwarding_headers(self):
        trusted = parse_trusted_proxy_cidrs("10.0.0.0/8")
        self.assertEqual(
            resolve_client_ip("203.0.113.9", "198.51.100.4", trusted),
            "203.0.113.9",
        )
        self.assertEqual(
            resolve_client_ip("10.1.2.3", "garbage, 198.51.100.4", trusted),
            "10.1.2.3",
        )

    def test_rejects_invalid_trusted_proxy_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "Invalid network"):
            parse_trusted_proxy_cidrs("not-a-network")


class GunicornSecurityTests(unittest.TestCase):
    def test_request_parser_limits_are_conservative(self):
        config = runpy.run_path(
            os.path.join(os.path.dirname(__file__), "gunicorn.conf.py")
        )
        self.assertEqual(config["limit_request_line"], 4094)
        self.assertEqual(config["limit_request_fields"], 100)
        self.assertEqual(config["limit_request_field_size"], 8190)


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
