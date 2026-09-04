from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from typing import NamedTuple
from urllib.parse import urlsplit


TRUE_VALUES = frozenset({"1", "true", "yes"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0"})


class BackendSettings(NamedTuple):
    db_path: str
    database_url: str | None
    maintenance_mode: bool
    public_site_url: str
    api_origin: str
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    bootstrap_admin_name: str
    redis_url: str | None
    trusted_proxy_cidrs: str
    max_content_length: int


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def optional_value(environment: Mapping[str, str], name: str) -> str | None:
    return environment.get(name, "").strip() or None


def load_settings(
    base_dir: str,
    environment: Mapping[str, str] | None = None,
) -> BackendSettings:
    environment = os.environ if environment is None else environment
    db_path = (
        environment.get("UA_HOMES_DB_PATH", "").strip()
        or os.path.join(base_dir, "ua_homes.db")
    )
    database_url = optional_value(environment, "DATABASE_URL")
    if parse_bool(environment.get("UA_HOMES_REQUIRE_POSTGRES")) and not database_url:
        raise RuntimeError(
            "DATABASE_URL must be set when UA_HOMES_REQUIRE_POSTGRES is enabled."
        )

    max_content_length_raw = environment.get(
        "UA_HOMES_MAX_CONTENT_LENGTH", "12582912"
    ).strip()
    try:
        max_content_length = int(max_content_length_raw)
    except ValueError as exc:
        raise RuntimeError("UA_HOMES_MAX_CONTENT_LENGTH must be an integer.") from exc
    if max_content_length < 1_048_576:
        raise RuntimeError(
            "UA_HOMES_MAX_CONTENT_LENGTH must be at least 1048576 bytes."
        )

    redis_url = optional_value(environment, "REDIS_URL")
    runtime_name = (
        environment.get("RAILWAY_ENVIRONMENT_NAME")
        or environment.get("RAILWAY_ENVIRONMENT")
        or environment.get("FLASK_ENV")
        or environment.get("ENVIRONMENT")
        or ""
    ).strip().lower()
    if runtime_name in {"production", "prod"} and not redis_url:
        raise RuntimeError(
            "REDIS_URL must be set for production deployments."
        )

    return BackendSettings(
        db_path=db_path,
        database_url=database_url,
        maintenance_mode=parse_bool(environment.get("UA_HOMES_MAINTENANCE_MODE")),
        public_site_url=environment.get("UA_HOMES_PUBLIC_URL", "").strip().rstrip("/"),
        api_origin=environment.get("UA_HOMES_API", "").strip().rstrip("/"),
        bootstrap_admin_email=environment.get(
            "UA_HOMES_BOOTSTRAP_ADMIN_EMAIL", ""
        ).strip().lower(),
        bootstrap_admin_password=environment.get(
            "UA_HOMES_BOOTSTRAP_ADMIN_PASSWORD", ""
        ).strip(),
        bootstrap_admin_name=(
            environment.get("UA_HOMES_BOOTSTRAP_ADMIN_NAME", "Admin").strip()
            or "Admin"
        ),
        redis_url=redis_url,
        trusted_proxy_cidrs=environment.get(
            "UA_HOMES_TRUSTED_PROXY_CIDRS", ""
        ).strip(),
        max_content_length=max_content_length,
    )


def production_secret_required(
    database_url: str | None,
    public_site_url: str,
    environment: Mapping[str, str] | None = None,
) -> bool:
    environment = os.environ if environment is None else environment
    runtime_name = (
        environment.get("RAILWAY_ENVIRONMENT_NAME")
        or environment.get("RAILWAY_ENVIRONMENT")
        or environment.get("FLASK_ENV")
        or environment.get("ENVIRONMENT")
        or ""
    ).strip().lower()
    if runtime_name in {"production", "prod"} or database_url:
        return True
    if public_site_url:
        try:
            host = (urlsplit(public_site_url).hostname or "").lower()
        except ValueError:
            host = ""
        if host and host not in LOCAL_HOSTS:
            return True
    return False


def resolve_secret(
    database_url: str | None,
    public_site_url: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    environment = os.environ if environment is None else environment
    configured_secret = environment.get("UA_HOMES_SECRET", "").strip()
    if configured_secret:
        return configured_secret
    if production_secret_required(database_url, public_site_url, environment):
        raise RuntimeError("UA_HOMES_SECRET must be set for production deployments.")
    return secrets.token_hex(32)
