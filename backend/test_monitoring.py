import os
import unittest
from unittest import mock

from werkzeug.exceptions import BadRequest, TooManyRequests

from backend import monitoring


class MonitoringTest(unittest.TestCase):
    def test_missing_dsn_is_disabled_and_healthy(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(monitoring.initialize_sentry())
            self.assertEqual(
                monitoring.monitoring_state(),
                {
                    "provider": "sentry",
                    "enabled": False,
                    "environment": "development",
                    "release_configured": False,
                },
            )

    def test_enabled_configuration_passes_release_environment_and_conservative_rates(self):
        with mock.patch.dict(
            os.environ,
            {
                "SENTRY_DSN": "https://public@example.ingest.sentry.io/1",
                "SENTRY_ENVIRONMENT": "test",
                "SENTRY_RELEASE": "release-test",
            },
            clear=True,
        ), mock.patch("sentry_sdk.init") as init:
            self.assertTrue(monitoring.initialize_sentry())
            options = init.call_args.kwargs
            self.assertEqual(options["environment"], "test")
            self.assertEqual(options["release"], "release-test")
            self.assertEqual(options["traces_sample_rate"], 0.01)
            self.assertEqual(options["profiles_sample_rate"], 0.0)
            self.assertFalse(options["send_default_pii"])
            self.assertIs(options["before_send"], monitoring.before_send)

    def test_expected_http_failures_are_filtered(self):
        event = {"exception": {"values": [{"type": "BadRequest"}]}}
        self.assertIsNone(monitoring.before_send(event, {"exc_info": (BadRequest, BadRequest(), None)}))
        self.assertIsNone(
            monitoring.before_send({}, {"exc_info": (TooManyRequests, TooManyRequests(), None)})
        )
        self.assertIsNone(
            monitoring.before_send({"tags": {"http.status_code": "422"}}, None)
        )

    def test_event_is_scrubbed_without_mutating_error_diagnostics(self):
        event = {
            "message": "database connection failed",
            "user": {"email": "person@example.test"},
            "request": {
                "url": "https://ua-dim.com/api/listings?token=secret&email=x",
                "query_string": "token=secret",
                "cookies": {"session": "secret"},
                "headers": {
                    "Authorization": "Bearer secret",
                    "User-Agent": "test-agent",
                },
                "data": {
                    "password": "secret",
                    "phone": "+380501234567",
                    "title": "safe listing title",
                    "message": "private inquiry",
                },
            },
            "extra": {"upload_url": "signed", "attempt": 2},
        }
        result = monitoring.before_send(event, None)
        self.assertEqual(result["message"], "database connection failed")
        self.assertNotIn("user", result)
        self.assertEqual(result["request"]["url"], "https://ua-dim.com/api/listings")
        self.assertEqual(result["request"]["query_string"], "")
        self.assertEqual(result["request"]["headers"]["Authorization"], "[Filtered]")
        self.assertEqual(result["request"]["headers"]["User-Agent"], "test-agent")
        self.assertEqual(result["request"]["data"]["password"], "[Filtered]")
        self.assertEqual(result["request"]["data"]["title"], "safe listing title")
        self.assertEqual(result["extra"]["upload_url"], "[Filtered]")

    def test_health_transactions_are_not_sampled(self):
        self.assertIsNone(
            monitoring.before_send_transaction(
                {"request": {"url": "https://api.example/api/health"}}, None
            )
        )
        event = {"request": {"url": "https://api.example/api/listings"}}
        self.assertIs(monitoring.before_send_transaction(event, None), event)

    def test_invalid_rates_use_conservative_defaults(self):
        with mock.patch.dict(
            os.environ,
            {"SENTRY_TRACES_SAMPLE_RATE": "many", "SENTRY_PROFILES_SAMPLE_RATE": "2"},
            clear=True,
        ):
            self.assertEqual(monitoring._sample_rate("SENTRY_TRACES_SAMPLE_RATE", 0.01), 0.01)
            self.assertEqual(monitoring._sample_rate("SENTRY_PROFILES_SAMPLE_RATE", 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
