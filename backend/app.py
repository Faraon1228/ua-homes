from __future__ import annotations
"""UA Homes backend — Flask + SQLite (dev) / PostgreSQL (prod).
Security: bcrypt passwords, JWT auth, rate limiting, CORS, parameterised queries.

Environment variables:
  UA_HOMES_SECRET     — JWT signing secret (required in production; auto-generated only for local/dev fallback)
  UA_HOMES_PUBLIC_URL — Canonical public URL for SEO/CORS
  UA_HOMES_DB_PATH    — Absolute path to the SQLite file. Point it at a mounted
                        persistent volume in production, otherwise the database is
                        wiped on every redeploy. Defaults to ./ua_homes.db.
  DATABASE_URL        — PostgreSQL DSN (e.g. postgres://user:pass@host/db).
                        If absent, falls back to local SQLite ua_homes.db.
  REDIS_URL           — Redis DSN for rate-limiter shared state across workers.
                        If absent, falls back to in-process memory (dev only).
"""
import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import sqlite3
import secrets
import statistics
import datetime
import tempfile
import threading
import time
import sys
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from html import escape
from functools import wraps
from typing import NamedTuple
from urllib.parse import quote, unquote, urlencode, urlsplit

import bcrypt
import jwt
from flask import Flask, Response, g, jsonify, request, send_file
from flask_limiter import Limiter
from werkzeug.exceptions import RequestEntityTooLarge

if __package__:
    from .configuration import load_settings, production_secret_required, resolve_secret
    from .client_identity import parse_trusted_proxy_cidrs, request_client_ip
    from .monitoring import bind_request_context, initialize_sentry, monitoring_state
    from .security_policy import (
        SECURITY_HEADERS,
        build_html_csp,
        cors_origins,
        response_security_headers,
    )
    from .time_helpers import legacy_utc_now
else:
    from configuration import load_settings, production_secret_required, resolve_secret
    from client_identity import parse_trusted_proxy_cidrs, request_client_ip
    from monitoring import bind_request_context, initialize_sentry, monitoring_state
    from security_policy import (
        SECURITY_HEADERS,
        build_html_csp,
        cors_origins,
        response_security_headers,
    )
    from time_helpers import legacy_utc_now

# Optional: Image optimization (Pillow)
try:
    from PIL import Image
    import io
    HAS_IMAGE_OPTIMIZATION = True
except ImportError:
    HAS_IMAGE_OPTIMIZATION = False

# ─── Config ──────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SETTINGS = load_settings(BASE_DIR)
DB_PATH = _SETTINGS.db_path
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
DATABASE_URL = _SETTINGS.database_url
MAINTENANCE_MODE = _SETTINGS.maintenance_mode
PUBLIC_SITE_URL = _SETTINGS.public_site_url
API_ORIGIN = _SETTINGS.api_origin
BOOTSTRAP_ADMIN_EMAIL = _SETTINGS.bootstrap_admin_email
BOOTSTRAP_ADMIN_PASSWORD = _SETTINGS.bootstrap_admin_password
BOOTSTRAP_ADMIN_NAME = _SETTINGS.bootstrap_admin_name


def _legacy_liqpay_environment() -> str:
    public_key = os.environ.get("LIQPAY_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("LIQPAY_PRIVATE_KEY", "").strip()
    if public_key.startswith("sandbox_") and private_key.startswith("sandbox_"):
        return "sandbox"
    if public_key and private_key:
        return "live"
    return "disabled"


def _production_secret_required() -> bool:
    return production_secret_required(DATABASE_URL, PUBLIC_SITE_URL)


SECRET_KEY = resolve_secret(DATABASE_URL, PUBLIC_SITE_URL)
JWT_ALGO   = "HS256"
JWT_EXP_H  = 72
ALERT_VERIFY_TTL_HOURS = 24
ALERT_VERIFY_COOLDOWN_MINUTES = 30
ALERT_ANONYMOUS_EMAIL_CAP = 5
ALERT_USER_CAP = 20
ALERT_DISPATCH_BATCH_SIZE = 200
ALERT_RECIPIENT_RUN_CAP = 10

# Redis DSN — if set, rate-limiter stores counters in Redis (safe for multi-worker).
REDIS_URL = _SETTINGS.redis_url
TRUSTED_PROXY_NETWORKS = parse_trusted_proxy_cidrs(_SETTINGS.trusted_proxy_cidrs)
_REDIS_CACHE = None
_REDIS_CACHE_DISABLED = False
_REPORT_CACHE_MAX_ENTRIES = 1024
_REPORT_CACHE: OrderedDict[str, tuple[float, object]] = OrderedDict()
_REPORT_CACHE_LOCK = threading.Lock()

# S3 Configuration for Direct Upload (Presigned URLs) — solves scaling issue with base64 encoding
# Supports: AWS S3, Cloudinary, MinIO, or any S3-compatible storage
# When S3 is configured, frontend uploads directly to S3, bypassing backend (no more base64 bloat)
S3_ENABLED = bool(os.environ.get("S3_BUCKET") or os.environ.get("CLOUDINARY_URL"))
S3_BUCKET = os.environ.get("S3_BUCKET", "").strip() or None
S3_REGION = os.environ.get("S3_REGION", "us-east-1").strip()
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "").strip() or None
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "").strip() or None
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "").strip() or None  # For MinIO or custom S3
S3_PUBLIC_BASE_URL = os.environ.get("S3_PUBLIC_BASE_URL", "").strip().rstrip("/") or None
CLOUDINARY_URL: str | None = os.environ.get("CLOUDINARY_URL", "").strip() or None


def _cloudinary_upload_preset() -> str | None:
    preset = os.environ.get("CLOUDINARY_UPLOAD_PRESET", "").strip()
    if not preset:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]+", preset):
        return preset
    print("[Cloudinary] Ignoring invalid CLOUDINARY_UPLOAD_PRESET value")
    return None

# Listing media upload limits
MAX_UPLOAD_SIZE = 10_485_760  # 10 MB per image
MAX_VIDEO_UPLOAD_SIZE = 104_857_600  # 100 MB per video
MAX_IMAGES_PER_LISTING = 8
MAX_VIDEOS_PER_LISTING = 2
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/avif",
    "image/heic",
    "image/heif",
    "image/gif",
    "image/bmp",
    "image/tiff",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}


def normalize_image_content_type(filename: str, content_type: str | None) -> str:
    normalized = (content_type or "").strip().lower()
    if normalized in {"image/jpg", "image/jpe"}:
        return "image/jpeg"
    if normalized in ALLOWED_IMAGE_TYPES:
        return normalized
    if normalized.startswith("image/"):
        return normalized

    guessed = (mimetypes.guess_type(filename or "")[0] or "").strip().lower()
    if guessed in {"image/jpg", "image/jpe"}:
        return "image/jpeg"
    if guessed in ALLOWED_IMAGE_TYPES:
        return guessed

    extension = (os.path.splitext(filename or "")[1] or "").lower()
    extension_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }
    return extension_map.get(extension, "")


def normalize_video_content_type(filename: str, content_type: str | None) -> str:
    normalized = (content_type or "").strip().lower()
    if normalized in ALLOWED_VIDEO_TYPES:
        return normalized

    guessed = (mimetypes.guess_type(filename or "")[0] or "").strip().lower()
    if guessed in ALLOWED_VIDEO_TYPES:
        return guessed

    extension = (os.path.splitext(filename or "")[1] or "").lower()
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
    }.get(extension, "")


def normalize_media_content_type(filename: str, content_type: str | None) -> tuple[str, str]:
    image_type = normalize_image_content_type(filename, content_type)
    if image_type in ALLOWED_IMAGE_TYPES:
        return image_type, "image"
    video_type = normalize_video_content_type(filename, content_type)
    if video_type in ALLOWED_VIDEO_TYPES:
        return video_type, "video"
    return "", ""


def _cors_origins() -> list[str | re.Pattern[str]]:
    return cors_origins(is_production=_production_secret_required())

def _build_html_csp(nonce: str = "") -> str:
    return build_html_csp(PUBLIC_SITE_URL, API_ORIGIN, nonce=nonce)


def _bootstrap_admin_user(db) -> None:
    if not BOOTSTRAP_ADMIN_EMAIL or not BOOTSTRAP_ADMIN_PASSWORD:
        return

    email = BOOTSTRAP_ADMIN_EMAIL
    password = BOOTSTRAP_ADMIN_PASSWORD
    name = BOOTSTRAP_ADMIN_NAME
    # Bootstrap credentials are only for creating the configured account once.
    # Never use an environment variable to reset or re-elevate an established
    # account during every process start.
    if db.execute("SELECT 1 FROM users WHERE email = ? LIMIT 1", (email,)).fetchone():
        return

    password_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("utf-8")
    db.execute(
        "INSERT INTO users (name, email, password, password_hash, role, status) VALUES (?, ?, ?, ?, 'admin', 'active')",
        (name, email, password_hash, password_hash),
    )
    db.commit()


def _password_matches(candidate: str, stored_value: str | None) -> bool:
    if not stored_value:
        return False
    stored = str(stored_value)
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(candidate.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    return candidate == stored

# ─── Database adapter ────────────────────────────────────────────────────────
# Thin compatibility shim so the rest of the app never needs to know which DB
# engine is being used.  Both sqlite3.Row and psycopg2's DictRow support dict().

class _DbCursorProxy:
    def __init__(self, connection_proxy, cursor, is_postgres: bool):
        self._connection_proxy = connection_proxy
        self._cursor = cursor
        self._is_postgres = is_postgres
        self._lastrowid = None

    def _translate_query(self, query: str) -> str:
        if not self._is_postgres or not isinstance(query, str):
            return query
        return re.sub(r"(?<!\?)\?(?!\?)", "%s", query)

    def execute(self, query, params=None):
        translated = self._translate_query(query)
        if params is None:
            self._cursor.execute(translated)
        else:
            self._cursor.execute(translated, params)
        if self._is_postgres and self._looks_like_insert(translated):
            savepoint = "ua_dim_lastval"
            self._cursor.execute(f"SAVEPOINT {savepoint}")
            try:
                self._cursor.execute("SELECT LASTVAL() AS lastrowid")
                row = self._cursor.fetchone()
                value = row.get("lastrowid") if hasattr(row, "get") else (row[0] if row else None)
                self._lastrowid = int(value) if value is not None else None
            except Exception:
                self._cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._lastrowid = None
            finally:
                self._cursor.execute(f"RELEASE SAVEPOINT {savepoint}")
        return self

    def executemany(self, query, params):
        translated = self._translate_query(query)
        self._cursor.executemany(translated, params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        if size is None:
            return self._cursor.fetchmany()
        return self._cursor.fetchmany(size)

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        if self._is_postgres:
            return self._lastrowid
        return getattr(self._cursor, "lastrowid", None)

    def close(self):
        self._cursor.close()

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    @staticmethod
    def _looks_like_insert(query: str) -> bool:
        if not query:
            return False
        return query.lstrip().upper().startswith("INSERT")


class _DbConnectionProxy:
    def __init__(self, conn, is_postgres: bool):
        self._conn = conn
        self._is_postgres = is_postgres
        self._row_factory = None

    def cursor(self):
        if self._is_postgres:
            import psycopg2.extras
            cursor = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        else:
            cursor = self._conn.cursor()
        return _DbCursorProxy(self, cursor, self._is_postgres)

    def execute(self, query, params=None):
        cursor = self.cursor()
        cursor.execute(query, params)
        return cursor

    def executemany(self, query, params):
        cursor = self.cursor()
        cursor.executemany(query, params)
        return cursor

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._row_factory = value
        if not self._is_postgres:
            self._conn.row_factory = value

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _is_postgres() -> bool:
    return DATABASE_URL is not None


def get_db():
    """Return a per-request DB connection (stored in Flask's g)."""
    if "db" not in g:
        if _is_postgres():
            try:
                import psycopg2
                conn = psycopg2.connect(DATABASE_URL)
                conn.autocommit = False
            except ImportError:
                raise RuntimeError(
                    "psycopg2 is not installed. "
                    "Add 'psycopg2-binary' to requirements.txt or unset DATABASE_URL."
                )
            wrapped = _DbConnectionProxy(conn, True)
        else:
            conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            wrapped = _DbConnectionProxy(conn, False)
        g.db = wrapped
    return g.db


def _cache_namespace_client():
    global _REDIS_CACHE, _REDIS_CACHE_DISABLED
    if _REDIS_CACHE_DISABLED:
        return None
    if _REDIS_CACHE is not None:
        return _REDIS_CACHE
    if not REDIS_URL:
        return None
    try:
        import redis

        _REDIS_CACHE = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        return _REDIS_CACHE
    except ImportError:
        app.logger.warning("Redis cache unavailable: redis package is not installed")
    except Exception as exc:
        app.logger.warning("Redis cache unavailable: %s", exc)
    _REDIS_CACHE_DISABLED = True
    return None


def cached_json_get(key: str):
    client = _cache_namespace_client()
    if client is not None:
        try:
            payload = client.get(key)
        except Exception as exc:
            app.logger.warning("Redis cache read failed for %s: %s", key, exc)
            return None
        if payload is None:
            return None
        return json.loads(payload)

    now = time.time()
    with _REPORT_CACHE_LOCK:
        cached = _REPORT_CACHE.get(key)
        if not cached:
            return None
        expires_at, value = cached
        if expires_at <= now:
            _REPORT_CACHE.pop(key, None)
            return None
        _REPORT_CACHE.move_to_end(key)
        return value


def cached_json_set(key: str, value, ttl_seconds: int) -> None:
    client = _cache_namespace_client()
    if client is not None:
        try:
            client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
            return
        except Exception as exc:
            app.logger.warning("Redis cache write failed for %s: %s", key, exc)

    with _REPORT_CACHE_LOCK:
        _REPORT_CACHE[key] = (time.time() + ttl_seconds, value)
        _REPORT_CACHE.move_to_end(key)
        now = time.time()
        for cached_key, (cached_expires_at, _) in list(_REPORT_CACHE.items()):
            if cached_expires_at <= now:
                _REPORT_CACHE.pop(cached_key, None)
        while len(_REPORT_CACHE) > _REPORT_CACHE_MAX_ENTRIES:
            _REPORT_CACHE.popitem(last=False)


def cache_delete_prefix(prefix: str) -> None:
    client = _cache_namespace_client()
    if client is not None:
        try:
            for key in client.scan_iter(match=f"{prefix}*"):
                client.delete(key)
            return
        except Exception as exc:
            app.logger.warning("Redis cache delete failed for %s: %s", prefix, exc)

    with _REPORT_CACHE_LOCK:
        for key in [key for key in _REPORT_CACHE if key.startswith(prefix)]:
            _REPORT_CACHE.pop(key, None)


def _refresh_lead_funnel_summaries(db) -> None:
    db.execute("DELETE FROM lead_funnel_daily_metrics")
    db.execute("DELETE FROM lead_funnel_listing_metrics")
    db.execute("DELETE FROM lead_funnel_session_rollups")

    db.execute(
        """
        INSERT INTO lead_funnel_daily_metrics (day, source, listing_type, event, event_count)
        SELECT
            DATE(created_at) AS day,
            COALESCE(NULLIF(source, ''), 'unknown') AS source,
            COALESCE(NULLIF(listing_type, ''), 'unknown') AS listing_type,
            event,
            COUNT(*) AS event_count
        FROM lead_funnel_events
        GROUP BY DATE(created_at), COALESCE(NULLIF(source, ''), 'unknown'), COALESCE(NULLIF(listing_type, ''), 'unknown'), event
        """
    )
    db.execute(
        """
        INSERT INTO lead_funnel_listing_metrics (day, listing_id, event, event_count)
        SELECT
            DATE(created_at) AS day,
            listing_id,
            event,
            COUNT(*) AS event_count
        FROM lead_funnel_events
        WHERE listing_id IS NOT NULL
        GROUP BY DATE(created_at), listing_id, event
        """
    )
    db.execute(
        """
        INSERT INTO lead_funnel_session_rollups (session_id, source, route_applies, first_route_at, submit_at, last_event_at)
        SELECT
            session_id,
            COALESCE(MAX(CASE WHEN event = 'route_apply' THEN source END), MAX(source), 'unknown') AS source,
            SUM(CASE WHEN event = 'route_apply' THEN 1 ELSE 0 END) AS route_applies,
            MIN(CASE WHEN event = 'route_apply' THEN created_at END) AS first_route_at,
            MIN(CASE WHEN event = 'lead_submit' THEN created_at END) AS submit_at,
            MAX(created_at) AS last_event_at
        FROM lead_funnel_events
        WHERE session_id IS NOT NULL
        GROUP BY session_id
        """
    )


def _refresh_listing_city_summary(db) -> None:
    db.execute("DELETE FROM listing_city_summary")
    db.execute(
        f"""
        INSERT INTO listing_city_summary (city, published_count, price_sum, avg_price, updated_at)
        SELECT
            city,
            COUNT(*) AS published_count,
            COALESCE(SUM(price), 0) AS price_sum,
            COALESCE(ROUND(AVG(price)), 0) AS avg_price,
            {db_now_expr()}
        FROM listings
        WHERE status = 'published'
        GROUP BY city
        """
    )


def _refresh_user_growth_summary(db) -> None:
    db.execute("DELETE FROM user_growth_daily")
    db.execute(
        f"""
        INSERT INTO user_growth_daily (day, user_count, updated_at)
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS user_count,
            {db_now_expr()}
        FROM users
        GROUP BY DATE(created_at)
        """
    )


def _upsert_lead_funnel_summary(db, *, day: str, source: str, listing_type: str, event: str, listing_id: int | None, created_at: str, session_id: str | None) -> None:
    db.execute(
        """
        INSERT INTO lead_funnel_daily_metrics (day, source, listing_type, event, event_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(day, source, listing_type, event)
        DO UPDATE SET event_count = lead_funnel_daily_metrics.event_count + 1
        """,
        (day, source, listing_type, event),
    )
    if listing_id is not None:
        db.execute(
            """
            INSERT INTO lead_funnel_listing_metrics (day, listing_id, event, event_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(day, listing_id, event)
            DO UPDATE SET event_count = lead_funnel_listing_metrics.event_count + 1
            """,
            (day, listing_id, event),
        )
    if session_id:
        existing = db.execute(
            "SELECT session_id, source, route_applies, first_route_at, submit_at, last_event_at FROM lead_funnel_session_rollups WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if existing:
            route_applies = int(existing["route_applies"] or 0) + (1 if event == "route_apply" else 0)
            first_route_at = existing["first_route_at"]
            if event == "route_apply" and not first_route_at:
                first_route_at = created_at
            submit_at = existing["submit_at"]
            if event == "lead_submit" and not submit_at:
                submit_at = created_at
            db.execute(
                """
                UPDATE lead_funnel_session_rollups
                SET source = ?,
                    route_applies = ?,
                    first_route_at = COALESCE(first_route_at, ?),
                    submit_at = COALESCE(submit_at, ?),
                    last_event_at = ?
                WHERE session_id = ?
                """,
                (
                    source or existing["source"] or "unknown",
                    route_applies,
                    first_route_at,
                    submit_at,
                    created_at,
                    session_id,
                ),
            )
        else:
            db.execute(
                """
                INSERT INTO lead_funnel_session_rollups
                (session_id, source, route_applies, first_route_at, submit_at, last_event_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    source,
                    1 if event == "route_apply" else 0,
                    created_at if event == "route_apply" else None,
                    created_at if event == "lead_submit" else None,
                    created_at,
                ),
            )


def db_placeholder() -> str:
    """Return the correct positional placeholder for the current DB driver."""
    return "%s" if _is_postgres() else "?"


def db_now_expr(offset_days: int | None = None) -> str:
    """Return a DB-safe SQL expression for the current timestamp."""
    if _is_postgres():
        if offset_days is None:
            return "CURRENT_TIMESTAMP"
        suffix = "day" if abs(offset_days) == 1 else "days"
        return f"CURRENT_TIMESTAMP - INTERVAL '{abs(offset_days)} {suffix}'"
    if offset_days is None:
        return "datetime('now')"
    sign = "-" if offset_days >= 0 else "+"
    return f"datetime('now', '{sign}{abs(offset_days)} days')"


def db_text_timestamp_expr(offset_days: int | None = None) -> str:
    """Return the current timestamp with the TEXT type used by the shared schema."""
    expression = db_now_expr(offset_days)
    return f"CAST({expression} AS TEXT)" if _is_postgres() else expression


def db_timestamp_column_expr(column: str) -> str:
    """Return a TEXT timestamp column converted for chronological comparison."""
    return f"{column}::timestamptz" if _is_postgres() else column


def _is_db_integrity_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    pgcode = getattr(exc, "pgcode", None)
    sqlstate = getattr(exc, "sqlstate", None)
    return pgcode in {"23505", "23503", "23502"} or sqlstate in {"23505", "23503", "23502"}


def _is_db_unique_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return (
            getattr(exc, "sqlite_errorcode", None) in {1555, 2067}
            or str(exc).startswith("UNIQUE constraint failed:")
        )
    return getattr(exc, "pgcode", None) == "23505" or getattr(exc, "sqlstate", None) == "23505"


_PG_MIGRATION_LOCK_ID = 8_140_713_559_001


def _migrate_postgres_agency_profiles(cur) -> None:
    text_now_expr = db_text_timestamp_expr()
    cur.execute("""
        ALTER TABLE agency_profiles ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
        ALTER TABLE agency_profiles ADD COLUMN IF NOT EXISTS revision INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE agency_profiles ADD COLUMN IF NOT EXISTS updated_at TEXT;
    """)
    cur.execute(
        f"""
        UPDATE agency_profiles
        SET status = CASE WHEN status IN ('active', 'suspended') THEN status ELSE 'active' END,
            revision = CASE WHEN revision > 0 THEN revision ELSE 1 END,
            updated_at = COALESCE(updated_at, created_at, {text_now_expr})
        """
    )
    cur.execute(
        "ALTER TABLE agency_profiles ALTER COLUMN updated_at"
        f" SET DEFAULT {text_now_expr}"
    )
    cur.execute(
        "ALTER TABLE agency_profiles ALTER COLUMN updated_at SET NOT NULL"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_agency_profiles_kind_status"
        " ON agency_profiles(kind, status)"
    )


def _init_postgres_db():
    """Create the PostgreSQL schema on a fresh database."""
    import psycopg2
    import psycopg2.extras

    db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    db.autocommit = False
    try:
        cur = db.cursor()
        # Every Gunicorn worker imports this module and runs the migrations.
        # Without a lock the concurrent DDL statements deadlock each other.
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_PG_MIGRATION_LOCK_ID,))
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                name            TEXT    NOT NULL,
                email           TEXT    NOT NULL UNIQUE,
                password        TEXT    NOT NULL,
                password_hash   TEXT,
                role            TEXT    NOT NULL DEFAULT 'user',
                account_type    TEXT    NOT NULL DEFAULT 'owner',
                plan_id         TEXT    NOT NULL DEFAULT 'free',
                plan_expires_at TEXT,
                agency_slug     TEXT,
                auth_token_version INTEGER NOT NULL DEFAULT 0,
                status          TEXT    NOT NULL DEFAULT 'active',
                created_at      TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS listings (
                id             INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title          TEXT    NOT NULL,
                region         TEXT,
                city           TEXT    NOT NULL,
                district       TEXT    NOT NULL,
                property_type  TEXT    NOT NULL DEFAULT 'квартира',
                condition_type TEXT    NOT NULL DEFAULT 'вторинка',
                price          INTEGER NOT NULL,
                rooms          INTEGER NOT NULL,
                area           REAL    NOT NULL,
                floor          INTEGER NOT NULL DEFAULT 1,
                total_floors   INTEGER NOT NULL DEFAULT 1,
                year_built     INTEGER,
                e_oselya       INTEGER NOT NULL DEFAULT 0,
                views          INTEGER NOT NULL DEFAULT 0,
                images         TEXT    NOT NULL DEFAULT '[]',
                videos         TEXT    NOT NULL DEFAULT '[]',
                status         TEXT    NOT NULL DEFAULT 'draft',
                listing_type   TEXT    NOT NULL DEFAULT 'sale',
                source         TEXT    NOT NULL DEFAULT 'owner',
                agency_slug    TEXT,
                listing_status TEXT    NOT NULL DEFAULT 'active',
                has_photo_tour INTEGER NOT NULL DEFAULT 0,
                has_video_tour INTEGER NOT NULL DEFAULT 0,
                listing_highlights TEXT NOT NULL DEFAULT '[]',
                capture_mode   TEXT    NOT NULL DEFAULT 'off_site',
                verified_owner INTEGER NOT NULL DEFAULT 0,
                verified_phone INTEGER NOT NULL DEFAULT 0,
                verified_docs  INTEGER NOT NULL DEFAULT 0,
                owner_verification_status TEXT NOT NULL DEFAULT 'unverified',
                phone_verification_status TEXT NOT NULL DEFAULT 'unverified',
                moderation_status TEXT NOT NULL DEFAULT 'pending_review',
                moderation_reason TEXT,
                moderation_updated_at TEXT,
                listing_verification_status TEXT NOT NULL DEFAULT 'unverified',
                last_confirmed_at TEXT,
                freshness_reminder_sent_at TEXT,
                published_at  TEXT,
                latitude       REAL,
                longitude      REAL,
                description    TEXT    NOT NULL DEFAULT '',
                created_at     TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS reviews (
                id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                user_name  TEXT    NOT NULL,
                rating     INTEGER NOT NULL,
                comment    TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS listing_images (
                id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                image_url  TEXT    NOT NULL,
                "order"    INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS moderation_log (
                id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                admin_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action     TEXT    NOT NULL,
                reason     TEXT,
                created_at TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS listing_alerts (
                id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
                email        TEXT    NOT NULL,
                name         TEXT,
                filters      TEXT    NOT NULL,
                is_active    INTEGER NOT NULL DEFAULT 1,
                last_sent_at TEXT,
                last_sent_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
                last_scanned_at TEXT,
                last_scanned_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
                email_normalized TEXT,
                subscription_key TEXT UNIQUE,
                verification_token_hash TEXT,
                verification_expires_at TEXT,
                verification_sent_at TEXT,
                verified_at TEXT,
                unsubscribe_version INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS alert_delivery_receipts (
                alert_id INTEGER NOT NULL REFERENCES listing_alerts(id) ON DELETE CASCADE,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                channel TEXT NOT NULL,
                event_key TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT ({db_now_expr()}),
                PRIMARY KEY (alert_id, listing_id, channel, event_key)
            );

            CREATE TABLE IF NOT EXISTS push_devices (
                id          INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token       TEXT    NOT NULL UNIQUE,
                platform    TEXT    NOT NULL,
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL DEFAULT ({db_now_expr()}),
                last_seen_at TEXT   NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS user_favorites (
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT ({db_now_expr()}),
                PRIMARY KEY (user_id, listing_id)
            );

            CREATE TABLE IF NOT EXISTS alert_dispatch_runs (
                id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                trigger_type TEXT    NOT NULL,
                dry_run      INTEGER NOT NULL DEFAULT 0,
                listing_id   INTEGER REFERENCES listings(id) ON DELETE SET NULL,
                checked      INTEGER NOT NULL DEFAULT 0,
                matched      INTEGER NOT NULL DEFAULT 0,
                email_sent   INTEGER NOT NULL DEFAULT 0,
                push_sent    INTEGER NOT NULL DEFAULT 0,
                success      INTEGER NOT NULL DEFAULT 0,
                error_text   TEXT,
                started_at   TEXT    NOT NULL DEFAULT ({db_now_expr()}),
                finished_at  TEXT,
                duration_ms  INTEGER
            );

            CREATE TABLE IF NOT EXISTS system_status_snapshots (
                id                  INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                generated_at        TEXT NOT NULL,
                overall_status      TEXT NOT NULL,
                snapshot_json       TEXT NOT NULL,
                refresh_duration_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_system_status_snapshots_generated_at
                ON system_status_snapshots(generated_at);

            CREATE TABLE IF NOT EXISTS system_incidents (
                id                  INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                fingerprint         TEXT NOT NULL UNIQUE,
                component           TEXT NOT NULL,
                severity            TEXT NOT NULL,
                summary             TEXT NOT NULL,
                first_seen_at       TEXT NOT NULL,
                last_seen_at        TEXT NOT NULL,
                resolved_at         TEXT,
                status              TEXT NOT NULL DEFAULT 'open',
                notified_at         TEXT,
                notification_result TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_system_incidents_open
                ON system_incidents(status, component);

            CREATE TABLE IF NOT EXISTS lead_funnel_events (
                id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                listing_id   INTEGER REFERENCES listings(id) ON DELETE SET NULL,
                event        TEXT    NOT NULL,
                intent       TEXT    NOT NULL,
                source       TEXT    NOT NULL,
                listing_type TEXT,
                price        INTEGER,
                session_id   TEXT,
                created_at   TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS lead_funnel_daily_metrics (
                day TEXT NOT NULL,
                source TEXT NOT NULL,
                listing_type TEXT NOT NULL,
                event TEXT NOT NULL,
                event_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, source, listing_type, event)
            );

            CREATE TABLE IF NOT EXISTS lead_funnel_listing_metrics (
                day TEXT NOT NULL,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                event TEXT NOT NULL,
                event_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, listing_id, event)
            );

            CREATE TABLE IF NOT EXISTS lead_funnel_session_rollups (
                session_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                route_applies INTEGER NOT NULL DEFAULT 0,
                first_route_at TEXT,
                submit_at TEXT,
                last_event_at TEXT NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS lead_requests (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                lead_type TEXT NOT NULL,
                source TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                bank TEXT,
                project_slug TEXT,
                project_name TEXT,
                city TEXT,
                district TEXT,
                amount INTEGER,
                down_payment INTEGER,
                years INTEGER,
                e_oselya INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
                session_id TEXT,
                requester_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                preferred_channel TEXT NOT NULL DEFAULT 'phone',
                status TEXT NOT NULL DEFAULT 'new',
                response_message TEXT,
                responded_at TEXT,
                created_at TEXT NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS client_observability_events (
                id           INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                event_type   TEXT    NOT NULL,
                metric_name  TEXT,
                metric_value REAL,
                rating       TEXT,
                message      TEXT,
                stack        TEXT,
                source       TEXT,
                page_url     TEXT,
                session_id   TEXT,
                user_agent   TEXT,
                payload_json TEXT,
                created_at   TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS listing_city_summary (
                city TEXT PRIMARY KEY,
                published_count INTEGER NOT NULL DEFAULT 0,
                price_sum INTEGER NOT NULL DEFAULT 0,
                avg_price INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS user_growth_daily (
                day TEXT PRIMARY KEY,
                user_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS agency_profiles (
                id                    INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                slug                  TEXT    NOT NULL UNIQUE,
                name                  TEXT    NOT NULL,
                kind                  TEXT    NOT NULL DEFAULT 'agency',
                city                  TEXT    NOT NULL,
                specialization        TEXT    NOT NULL DEFAULT '',
                is_verified           INTEGER NOT NULL DEFAULT 0,
                status                TEXT    NOT NULL DEFAULT 'active',
                avg_response_minutes  INTEGER,
                team_size             INTEGER,
                completed_deals       INTEGER NOT NULL DEFAULT 0,
                last_verified_at      TEXT,
                revision              INTEGER NOT NULL DEFAULT 1,
                created_at            TEXT    NOT NULL DEFAULT ({db_text_timestamp_expr()}),
                updated_at            TEXT    NOT NULL DEFAULT ({db_text_timestamp_expr()})
            );

            CREATE TABLE IF NOT EXISTS premium_orders (
                id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                order_id   TEXT    NOT NULL UNIQUE,
                plan_id    TEXT    NOT NULL,
                amount     REAL,
                currency   TEXT    NOT NULL DEFAULT 'UAH',
                status     TEXT    NOT NULL DEFAULT 'pending',
                user_id    INTEGER,
                environment TEXT   NOT NULL DEFAULT 'disabled',
                provider_status TEXT,
                provider_payment_id TEXT,
                processed_at TEXT,
                paid_at TEXT,
                previous_plan_id TEXT,
                previous_plan_expires_at TEXT,
                activated_plan_expires_at TEXT,
                entitlement_chain_id TEXT,
                created_at TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS listing_reports (
                id                   INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                listing_id           INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                reporter_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reporter_fingerprint TEXT    NOT NULL,
                reason_code          TEXT    NOT NULL,
                details              TEXT    NOT NULL,
                status               TEXT    NOT NULL DEFAULT 'pending',
                idempotency_key      TEXT    NOT NULL UNIQUE,
                created_at           TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS listing_change_history (
                id         INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                field_name TEXT    NOT NULL,
                old_value  TEXT,
                new_value  TEXT,
                actor_type TEXT    NOT NULL DEFAULT 'system',
                created_at TEXT    NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id            INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                actor_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
                actor_role    TEXT NOT NULL,
                action        TEXT NOT NULL,
                permission    TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id   TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                request_id    TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT ({db_now_expr()})
            );

            CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_city ON listings(city);
            CREATE INDEX IF NOT EXISTS idx_listings_status_created_at ON listings(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_status_city ON listings(status, city);
            CREATE INDEX IF NOT EXISTS idx_listings_status_listing_type ON listings(status, listing_type);
            CREATE INDEX IF NOT EXISTS idx_listings_status_agency_slug ON listings(status, agency_slug);
            CREATE INDEX IF NOT EXISTS idx_listings_agency_created_at ON listings(agency_slug, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_status_published_at ON listings(status, published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);
            CREATE INDEX IF NOT EXISTS idx_listings_user_id ON listings(user_id);
            CREATE INDEX IF NOT EXISTS idx_listings_type ON listings(property_type);
            CREATE INDEX IF NOT EXISTS idx_reviews_listing_id ON reviews(listing_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_listing_created_at ON reviews(listing_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listing_images ON listing_images(listing_id);
            CREATE INDEX IF NOT EXISTS idx_moderation_log ON moderation_log(listing_id);
            CREATE INDEX IF NOT EXISTS idx_moderation_log_created_at ON moderation_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_status_e_oselya ON listings(status, e_oselya);
            CREATE INDEX IF NOT EXISTS idx_listings_status_listing_status ON listings(status, listing_status);
            CREATE INDEX IF NOT EXISTS idx_listings_status_verified ON listings(status, verified_owner, verified_phone, verified_docs);
            CREATE INDEX IF NOT EXISTS idx_listing_alerts_user ON listing_alerts(user_id);
            CREATE INDEX IF NOT EXISTS idx_listing_alerts_email ON listing_alerts(email);
            CREATE INDEX IF NOT EXISTS idx_listing_alerts_last_sent ON listing_alerts(last_sent_at);
            CREATE INDEX IF NOT EXISTS idx_alert_delivery_receipts_created ON alert_delivery_receipts(created_at);
            CREATE INDEX IF NOT EXISTS idx_push_devices_user ON push_devices(user_id, is_active);
            CREATE INDEX IF NOT EXISTS idx_push_devices_last_seen ON push_devices(last_seen_at);
            CREATE INDEX IF NOT EXISTS idx_user_favorites_listing ON user_favorites(listing_id);
            CREATE INDEX IF NOT EXISTS idx_user_favorites_created ON user_favorites(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_alert_dispatch_runs_started_at ON alert_dispatch_runs(started_at);
            CREATE INDEX IF NOT EXISTS idx_alert_dispatch_runs_success ON alert_dispatch_runs(success);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_created ON lead_funnel_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_created_source_event ON lead_funnel_events(created_at, source, event);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_source ON lead_funnel_events(source);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_source_created ON lead_funnel_events(source, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_event ON lead_funnel_events(event);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_listing ON lead_funnel_events(listing_id);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_daily_metrics_day ON lead_funnel_daily_metrics(day);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_daily_metrics_source_day ON lead_funnel_daily_metrics(source, day);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_daily_metrics_type_day ON lead_funnel_daily_metrics(listing_type, day);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_listing_metrics_day ON lead_funnel_listing_metrics(day);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_listing_metrics_listing ON lead_funnel_listing_metrics(listing_id);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_session_rollups_source ON lead_funnel_session_rollups(source);
            CREATE INDEX IF NOT EXISTS idx_lead_funnel_session_rollups_first_route ON lead_funnel_session_rollups(first_route_at);
            CREATE INDEX IF NOT EXISTS idx_lead_requests_created_at ON lead_requests(created_at);
            CREATE INDEX IF NOT EXISTS idx_lead_requests_type_created ON lead_requests(lead_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_lead_requests_project_slug ON lead_requests(project_slug);
            CREATE INDEX IF NOT EXISTS idx_lead_requests_session ON lead_requests(session_id);
            CREATE INDEX IF NOT EXISTS idx_client_observability_created ON client_observability_events(created_at);
            CREATE INDEX IF NOT EXISTS idx_client_observability_type_created ON client_observability_events(event_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_client_observability_metric_created ON client_observability_events(metric_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_listing_city_summary_count ON listing_city_summary(published_count DESC, city ASC);
            CREATE INDEX IF NOT EXISTS idx_user_growth_daily_day ON user_growth_daily(day);
            CREATE INDEX IF NOT EXISTS idx_agency_profiles_verified ON agency_profiles(is_verified);
            CREATE INDEX IF NOT EXISTS idx_agency_profiles_city ON agency_profiles(city);
            CREATE INDEX IF NOT EXISTS idx_premium_orders_status ON premium_orders(status);
            CREATE INDEX IF NOT EXISTS idx_listing_reports_listing ON listing_reports(listing_id);
            CREATE INDEX IF NOT EXISTS idx_listing_reports_status ON listing_reports(status);
            CREATE INDEX IF NOT EXISTS idx_listing_reports_dedupe ON listing_reports(listing_id, reporter_fingerprint, reason_code, created_at);
            CREATE INDEX IF NOT EXISTS idx_listing_change_history_listing ON listing_change_history(listing_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON admin_audit_log(actor_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_admin_audit_resource ON admin_audit_log(resource_type, resource_id, created_at DESC);
        """)

        # Backward-compatible migration for databases created before subscriptions.
        cur.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type    TEXT NOT NULL DEFAULT 'owner';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_id         TEXT NOT NULL DEFAULT 'free';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS agency_slug     TEXT;
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS region TEXT;
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS listing_verification_status TEXT NOT NULL DEFAULT 'unverified';
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS videos TEXT NOT NULL DEFAULT '[]';
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS last_confirmed_at TEXT;
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS freshness_reminder_sent_at TEXT;
        """)
        # The region column may not exist until the migration above runs (on
        # databases created before the region/settlement feature), so its
        # indexes must be created afterwards rather than in the initial
        # CREATE TABLE IF NOT EXISTS / CREATE INDEX block above.
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_listings_region ON listings(region);
            CREATE INDEX IF NOT EXISTS idx_listings_status_region ON listings(status, region);
        """)
        # Email / phone verification columns and password-reset columns (stage-2 auth hardening).
        cur.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified              INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verify_token          TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verify_expires        TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS phone                       TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verify_code          TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verify_expires        TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified              INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token_hash   TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires      TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_token_version           INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS environment         TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS provider_status     TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS provider_payment_id TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS processed_at        TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS paid_at             TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS previous_plan_id     TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS previous_plan_expires_at TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS activated_plan_expires_at TEXT;
            ALTER TABLE premium_orders ADD COLUMN IF NOT EXISTS entitlement_chain_id TEXT;
            ALTER TABLE lead_requests ADD COLUMN IF NOT EXISTS requester_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
            ALTER TABLE lead_requests ADD COLUMN IF NOT EXISTS preferred_channel TEXT NOT NULL DEFAULT 'phone';
            ALTER TABLE lead_requests ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'new';
            ALTER TABLE lead_requests ADD COLUMN IF NOT EXISTS response_message TEXT;
            ALTER TABLE lead_requests ADD COLUMN IF NOT EXISTS responded_at TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS last_sent_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS last_scanned_at TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS last_scanned_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS email_normalized TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS subscription_key TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS verification_token_hash TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS verification_expires_at TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS verification_sent_at TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS verified_at TEXT;
            ALTER TABLE listing_alerts ADD COLUMN IF NOT EXISTS unsubscribe_version INTEGER NOT NULL DEFAULT 0;
        """)
        _migrate_postgres_agency_profiles(cur)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_lead_requests_listing_status
                ON lead_requests(listing_id, status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_lead_requests_requester
                ON lead_requests(requester_user_id, created_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_listing_alerts_subscription_key
                ON listing_alerts(subscription_key);
            CREATE INDEX IF NOT EXISTS idx_listing_alerts_email_state
                ON listing_alerts(email_normalized, is_active);
            CREATE INDEX IF NOT EXISTS idx_listing_alerts_verification_token
                ON listing_alerts(verification_token_hash);
        """)
        cur.execute(
            "UPDATE listing_alerts SET email_normalized = LOWER(TRIM(email))"
            " WHERE email_normalized IS NULL"
        )
        cur.execute(
            "UPDATE premium_orders SET environment = %s"
            " WHERE environment IS NULL OR environment = ''"
            " OR (environment = 'disabled' AND status IN ('pending', 'success', 'sandbox'))",
            (_legacy_liqpay_environment(),),
        )
        cur.execute(
            """
            UPDATE premium_orders
            SET provider_status = status,
                status = 'paid',
                paid_at = COALESCE(paid_at, created_at),
                processed_at = COALESCE(processed_at, created_at),
                previous_plan_id = COALESCE(
                    previous_plan_id,
                    CASE
                        WHEN plan_id LIKE 'realtor_%' THEN 'realtor_free'
                        WHEN plan_id LIKE 'developer_%' THEN 'developer_free'
                        ELSE 'free'
                    END
                ),
                entitlement_chain_id = COALESCE(entitlement_chain_id, order_id)
            WHERE status IN ('success', 'sandbox')
            """
        )
        cur.execute(
            "UPDATE premium_orders SET entitlement_chain_id = order_id"
            " WHERE status = 'paid' AND entitlement_chain_id IS NULL"
        )
        cur.execute(
            "UPDATE users SET account_type = 'owner'"
            " WHERE account_type IS NULL OR account_type NOT IN ('owner', 'realtor', 'developer')"
        )
        cur.execute(
            "UPDATE users SET plan_id = CASE WHEN account_type = 'realtor' THEN 'realtor_free' WHEN account_type = 'developer' THEN 'developer_free' ELSE 'free' END"
            " WHERE plan_id IS NULL OR plan_id = ''"
        )
        cur.execute(
            "UPDATE listings SET listing_verification_status = 'unverified'"
            " WHERE listing_verification_status IS NULL"
            " OR listing_verification_status NOT IN ('unverified', 'pending', 'verified', 'rejected')"
        )
        if os.environ.get("UA_HOMES_SEED_DEMO_DATA", "").strip().lower() in {"1", "true", "yes"}:
            _seed_postgres(cur)
        else:
            _bootstrap_postgres_admin(cur)
        db.commit()
    finally:
        db.close()


def _seed_postgres(cur):
    """Populate a fresh PostgreSQL database with the same demo data as SQLite."""
    now = db_now_expr()

    cur.execute("SELECT COUNT(*) AS n FROM users")
    if cur.fetchone()["n"] == 0:
        demo_pw = bcrypt.hashpw(b"demo1234", bcrypt.gensalt(rounds=12)).decode()
        cur.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s) RETURNING id",
            ("UA Homes Demo", "demo@ua-dim.com", demo_pw),
        )
        demo_id = cur.fetchone()["id"]
        for listing_type, rows in (("sale", SEED_LISTINGS), ("rent", SEED_RENT_LISTINGS)):
            cur.executemany(
                f"""INSERT INTO listings
                   (user_id,title,city,district,property_type,condition_type,price,rooms,area,
                    floor,total_floors,year_built,e_oselya,images,description,latitude,longitude,
                    status,published_at,verified_owner,verified_phone,verified_docs,source,listing_type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                           'published',{now},1,1,1,'seed',%s)""",
                [(demo_id, *row, listing_type) for row in rows],
            )

    cur.execute("SELECT COUNT(*) AS n FROM agency_profiles")
    if cur.fetchone()["n"] == 0:
        cur.executemany(
            f"""
            INSERT INTO agency_profiles
            (slug, name, kind, city, specialization, is_verified, avg_response_minutes,
             team_size, completed_deals, last_verified_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, {now})
            """,
            [
                ("capital-alliance", "Capital Alliance", "agency", "Київ", "Преміум квартири та будинки", 1, 32, 24, 460),
                ("lviv-home-experts", "Lviv Home Experts", "agency", "Львів", "Сімейні квартири + єОселя", 1, 41, 16, 280),
                ("dnipro-urban-group", "Dnipro Urban Group", "developer", "Дніпро", "Новобудови комфорт+ класу", 1, 55, 32, 520),
                ("odesa-coast-build", "Odesa Coast Build", "developer", "Одеса", "Будинки та апартаменти біля моря", 1, 49, 18, 340),
            ],
        )

    # Keep demo rows publicly visible and enriched, mirroring the SQLite branch.
    cur.execute(
        """
        UPDATE listings
        SET status = 'published',
            published_at = COALESCE(published_at, created_at),
            verified_owner = 1,
            verified_phone = 1,
            verified_docs = 1,
            owner_verification_status = 'verified',
            phone_verification_status = 'verified',
            moderation_status = 'approved',
            moderation_reason = NULL,
            moderation_updated_at = COALESCE(moderation_updated_at, published_at, created_at),
            source = COALESCE(NULLIF(source, ''), 'seed'),
            agency_slug = CASE
                WHEN city = 'Київ' THEN 'capital-alliance'
                WHEN city = 'Львів' THEN 'lviv-home-experts'
                WHEN city = 'Дніпро' THEN 'dnipro-urban-group'
                WHEN city = 'Одеса' THEN 'odesa-coast-build'
                ELSE agency_slug
            END,
            listing_status = CASE
                WHEN id %% 4 = 0 THEN 'sold'
                WHEN id %% 5 = 0 THEN 'removed'
                ELSE 'active'
            END,
            has_photo_tour = CASE WHEN id %% 3 = 0 THEN 1 ELSE 0 END,
            has_video_tour = CASE WHEN id %% 4 = 0 THEN 1 ELSE 0 END
        WHERE user_id IN (SELECT id FROM users WHERE email = %s)
        """,
        ("demo@ua-dim.com",),
    )

    _bootstrap_postgres_admin(cur)


def _bootstrap_postgres_admin(cur):
    """Create the configured production administrator once."""
    if BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD:
        cur.execute("SELECT id FROM users WHERE email = %s LIMIT 1", (BOOTSTRAP_ADMIN_EMAIL,))
        existing = cur.fetchone()
        if not existing:
            password_hash = bcrypt.hashpw(
                BOOTSTRAP_ADMIN_PASSWORD.encode("utf-8"),
                bcrypt.gensalt(rounds=12),
            ).decode("utf-8")
            cur.execute(
                "INSERT INTO users (name, email, password, password_hash, role, status) VALUES (%s, %s, %s, %s, 'admin', 'active')",
                (
                    BOOTSTRAP_ADMIN_NAME,
                    BOOTSTRAP_ADMIN_EMAIL,
                    password_hash,
                    password_hash,
                ),
            )


# ─── App setup ───────────────────────────────────────────────────────────────

SENTRY_ENABLED = initialize_sentry()
app = Flask(__name__)

# Configure Cloudinary early so api_sign_request has credentials
if CLOUDINARY_URL:
    import cloudinary
    cloudinary.config(secure=True)  # Auto-loads from CLOUDINARY_URL environment variable


def csp_nonce() -> str:
    nonce = getattr(g, "csp_nonce", None)
    if nonce is None:
        nonce = secrets.token_urlsafe(24)
        g.csp_nonce = nonce
    return nonce


@app.before_request
def assign_request_id():
    g.request_started_at = time.perf_counter()
    incoming_request_id = request.headers.get("X-Request-ID", "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", incoming_request_id):
        g.request_id = incoming_request_id
    else:
        g.request_id = secrets.token_hex(12)
    g.csp_nonce = secrets.token_urlsafe(24)
    bind_request_context(
        g.request_id,
        request.method,
        request.url_rule.rule if request.url_rule else "unmatched",
    )


@app.before_request
def enforce_maintenance_mode():
    if (
        MAINTENANCE_MODE
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.path != "/api/operations/backup"
    ):
        response = jsonify(
            error="Сервіс тимчасово оновлюється. Спробуйте ще раз за хвилину.",
            code="maintenance",
        )
        response.status_code = 503
        response.headers["Retry-After"] = "60"
        return response
    return None


@app.before_request
def enforce_edge_origin_token():
    """Require the private edge token for API traffic when configured."""
    configured_token = os.environ.get("UA_HOMES_EDGE_TOKEN", "").strip()
    if (
        configured_token
        and request.path.startswith("/api/")
        and request.path != "/api/health"
        and not hmac.compare_digest(
            request.headers.get("X-UA-Edge-Token", ""),
            configured_token,
        )
    ):
        return jsonify(error="Direct API origin access is not allowed.", code="edge_required"), 403
    return None


# Rate-limiter storage: Redis when available (multi-worker safe), else in-memory.
_limiter_storage = f"redis://{REDIS_URL.replace('redis://','')}" if REDIS_URL else "memory://"
if REDIS_URL and not REDIS_URL.startswith("redis://"):
    _limiter_storage = REDIS_URL  # accept full DSN as-is

limiter = Limiter(
    lambda: request_client_ip(request, TRUSTED_PROXY_NETWORKS),
    app=app,
    # Public browsing endpoints: generous — real users never hit this.
    # Sensitive mutation endpoints keep tighter per-route limits below.
    default_limits=["1000 per minute"],
    storage_uri=_limiter_storage,
)
app.config["MAX_CONTENT_LENGTH"] = _SETTINGS.max_content_length


@app.before_request
def enforce_declared_request_size():
    if (
        request.content_length is not None
        and request.content_length > app.config["MAX_CONTENT_LENGTH"]
    ):
        raise RequestEntityTooLarge()


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_error):
    return jsonify(
        error="Тіло запиту перевищує дозволений розмір",
        code="request_too_large",
    ), 413

ALERTS_DISPATCH_KEY = os.environ.get("UA_HOMES_ALERTS_DISPATCH_KEY", "").strip()
ALERTS_PUSH_WEBHOOK_URL = os.environ.get("UA_HOMES_ALERTS_PUSH_WEBHOOK_URL", "").strip()
ALERTS_PUSH_WEBHOOK_BEARER = os.environ.get("UA_HOMES_ALERTS_PUSH_WEBHOOK_BEARER", "").strip()
FIREBASE_SERVICE_ACCOUNT_BASE64 = os.environ.get(
    "UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64", ""
).strip()
FIREBASE_PROJECT_ID = "ua-dim-production"
_FIREBASE_APP_NAME = "ua-homes-alerts"
_firebase_app = None
_firebase_init_failed = False
_firebase_init_lock = threading.Lock()

def _cache_control_for_request() -> str | None:
    if request.method != "GET":
        return None
    if request.headers.get("Authorization"):
        return "private, no-store"

    path = request.path.rstrip("/") or "/"
    if path == "/api/listings":
        return "public, max-age=30, stale-while-revalidate=120"
    if path.startswith("/api/listings/"):
        return "public, max-age=60, stale-while-revalidate=300"
    if path in {"/api/content", "/insights"} or path.startswith("/insights/"):
        return "public, max-age=300, stale-while-revalidate=3600"
    if path == "/api/agencies" or path.startswith("/api/agencies/") or path == "/agencies" or path.startswith("/agencies/"):
        return "public, max-age=300, stale-while-revalidate=3600"
    return None


def _allow_cors_for_request(response: Response) -> Response:
    origin = request.headers.get("Origin", "").strip()
    for header in (
        "Access-Control-Allow-Origin",
        "Access-Control-Allow-Credentials",
        "Access-Control-Allow-Methods",
        "Access-Control-Allow-Headers",
    ):
        response.headers.pop(header, None)
    if not origin:
        return response

    for allowed_origin in _cors_origins():
        if isinstance(allowed_origin, re.Pattern):
            if allowed_origin.match(origin):
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers.setdefault("Vary", "Origin")
                if request.method == "OPTIONS":
                    response.headers["Access-Control-Allow-Methods"] = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
                    requested_headers = request.headers.get("Access-Control-Request-Headers", "Content-Type, Authorization")
                    response.headers["Access-Control-Allow-Headers"] = requested_headers
                break
        elif allowed_origin == origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers.setdefault("Vary", "Origin")
            if request.method == "OPTIONS":
                response.headers["Access-Control-Allow-Methods"] = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
                requested_headers = request.headers.get("Access-Control-Request-Headers", "Content-Type, Authorization")
                response.headers["Access-Control-Allow-Headers"] = requested_headers
            break
    return response


@app.after_request
def apply_security_headers(response):
    request_started_at = getattr(g, "request_started_at", None)
    duration_ms = round(
        (time.perf_counter() - request_started_at) * 1000 if request_started_at is not None else 0,
        2,
    )
    response.headers.setdefault("X-Request-ID", getattr(g, "request_id", secrets.token_hex(12)))
    response.headers.setdefault("Server-Timing", f"app;dur={duration_ms}")
    response.headers.setdefault("X-Response-Time-Ms", str(duration_ms))
    is_secure = (
        request.is_secure
        or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    )
    headers = response_security_headers(
        is_secure=is_secure,
        is_html=response.mimetype == "text/html",
    )
    if "Content-Security-Policy" in headers:
        headers["Content-Security-Policy"] = _build_html_csp(csp_nonce())
    for header, value in headers.items():
        response.headers.setdefault(header, value)

    cache_control = _cache_control_for_request()
    if cache_control:
        response.headers["Cache-Control"] = cache_control
        if request.headers.get("Authorization"):
            response.headers.setdefault("Vary", "Authorization")

    response = _allow_cors_for_request(response)

    endpoint = request.endpoint or "unmatched"
    # Blueprint-registered views are exposed as "<blueprint_name>.<view_name>",
    # so compare against the unqualified view name to stay blueprint-agnostic.
    endpoint_view_name = endpoint.rsplit(".", 1)[-1]
    event_type = "api_request"
    if endpoint_view_name in {"get_presigned_upload_url", "confirm_uploaded_media", "abort_multipart_upload", "optimize_image"}:
        event_type = "media_upload"
    elif endpoint_view_name in {"create_lead_request", "create_listing_inquiry"} or endpoint_view_name.startswith("lead_"):
        event_type = "lead_request"
    log_payload = {
        "event": event_type,
        "request_id": getattr(g, "request_id", "unknown"),
        "method": request.method,
        "route": request.url_rule.rule if request.url_rule else request.path,
        "endpoint": endpoint,
        "status": response.status_code,
        "duration_ms": duration_ms,
        "database_engine": "postgresql" if _is_postgres() else "sqlite",
    }
    log_line = json.dumps(log_payload, ensure_ascii=False, separators=(",", ":"))
    if response.status_code >= 500:
        app.logger.error(log_line)
    elif event_type != "api_request" or duration_ms >= 1000:
        app.logger.info(log_line)

    return response


@app.get("/")
def root():
    site_url = public_app_url()
    return Response(
        f"""<!doctype html>
<html lang="uk">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>UA Homes API</title>
<body style="font-family:system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;padding:32px;line-height:1.5">
  <h1>UA Homes API</h1>
  <p>Основний сайт: <a href="{site_url}">{site_url}</a></p>
  <p>Health: <a href="/api/health">/api/health</a></p>
</body>
</html>""",
        mimetype="text/html",
    )

@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        if _is_postgres():
            try:
                if _exc is None:
                    db.commit()
                else:
                    db.rollback()
            finally:
                db.close()
        else:
            db.close()


# ─── Seed data ────────────────────────────────────────────────────────────────

PLACEHOLDER_LISTING_IMAGE = (
    "data:image/svg+xml;charset=utf-8,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 800'%3E"
    "%3Crect width='1200' height='800' fill='%23e2e8f0'/%3E"
    "%3Crect width='1200' height='120' fill='%232563eb'/%3E"
    "%3Ctext x='60' y='80' fill='white' font-family='Arial,sans-serif' font-size='54' font-weight='700'%3EUA-Dim%3C/text%3E"
    "%3Ctext x='60' y='220' fill='%231f2937' font-family='Arial,sans-serif' font-size='40' font-weight='700'%3EListing preview%3C/text%3E"
    "%3Ctext x='60' y='280' fill='%234b5563' font-family='Arial,sans-serif' font-size='28'%3EImage unavailable%3C/text%3E"
    "%3C/svg%3E"
)

IMG = PLACEHOLDER_LISTING_IMAGE


def _cloudinary_fallback_image_url() -> str | None:
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    if not cloud_name:
        match = re.search(r"cloudinary://[^@]+@([A-Za-z0-9_-]+)", CLOUDINARY_URL or "", re.IGNORECASE)
        if match:
            cloud_name = match.group(1)
    if not cloud_name:
        return None
    return f"https://res.cloudinary.com/{cloud_name}/image/upload/v1786173903/listings/6/62114b6a0810/real-photo-test.jpg"


def _svg_data_uri_for_seed(seed: str) -> str:
    seed_label = escape(seed or "listing", quote=True)
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 800'>"
        "<rect width='1200' height='800' fill='#0f172a'/>"
        "<rect width='1200' height='140' fill='#2563eb'/>"
        f"<text x='60' y='88' fill='white' font-family='Arial,sans-serif' font-size='54' font-weight='700'>UA-Dim</text>"
        f"<text x='60' y='230' fill='#f8fafc' font-family='Arial,sans-serif' font-size='42' font-weight='700'>Оголошення</text>"
        f"<text x='60' y='300' fill='#cbd5e1' font-family='Arial,sans-serif' font-size='26'>{seed_label}</text>"
        "<rect x='60' y='360' width='320' height='18' rx='9' fill='#334155'/>"
        "<rect x='60' y='395' width='240' height='18' rx='9' fill='#475569'/>"
        "</svg>"
    )
    return f"data:image/svg+xml;charset=utf-8,{quote(svg, safe='')}"


def demo_image_url(seed: str) -> str:
    cloudinary_url = _cloudinary_fallback_image_url()
    if cloudinary_url:
        return cloudinary_url

    if isinstance(seed, str) and seed.strip():
        seed_key = seed.strip()
        if re.fullmatch(r"[a-z0-9-]+", seed_key):
            return _svg_data_uri_for_seed(seed_key)

    base = (PUBLIC_SITE_URL or "").rstrip("/")
    try:
        host = (urlsplit(base).hostname or "").lower()
    except ValueError:
        host = ""
    if host in {"", "localhost", "127.0.0.1", "0.0.0.0"}:
        base = "http://localhost:5050"
    else:
        base = "https://ua-dim.com"
    return f"{base}/demo-images/{quote(seed, safe='')}.svg"


def legacy_demo_image_seed(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    match = re.search(r"/(?:api/)?demo-images/([^/]+)\.svg$", parsed.path or "")
    if match:
        return match.group(1)
    return None


def imgs(*ids):
    """Return a JSON array of first-party demo image URLs for deterministic seed media."""
    return json.dumps([demo_image_url(uid) for uid in ids])


def json_for_html_script(value) -> str:
    """Serialize JSON without allowing data to terminate an HTML script element."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


UKRAINIAN_REGIONS: list[str] = [
    "Вінницька",
    "Волинська",
    "Дніпропетровська",
    "Донецька",
    "Житомирська",
    "Закарпатська",
    "Запорізька",
    "Івано-Франківська",
    "Київська",
    "Кіровоградська",
    "Луганська",
    "Львівська",
    "Миколаївська",
    "Одеська",
    "Полтавська",
    "Рівненська",
    "Сумська",
    "Тернопільська",
    "Харківська",
    "Херсонська",
    "Хмельницька",
    "Черкаська",
    "Чернівецька",
    "Чернігівська",
    "Автономна Республіка Крим",
]

REGION_SETTLEMENTS_MAP: dict[str, list[str]] = {
    "Вінницька": ["Вінниця", "Гайсин", "Жмеринка", "Могилів-Подільський", "Тульчин", "Хмільник", "Козятин", "Ладижин"],
    "Волинська": ["Луцьк", "Володимир", "Камінь-Каширський", "Ковель", "Нововолинськ", "Маневичі"],
    "Дніпропетровська": ["Дніпро", "Кам'янське", "Кривий Ріг", "Нікополь", "Павлоград", "Самар", "Синельникове", "Жовті Води"],
    "Донецька": ["Донецьк", "Бахмут", "Волноваха", "Горлівка", "Кальміуське", "Краматорськ", "Маріуполь", "Покровськ", "Слов'янськ"],
    "Житомирська": ["Житомир", "Бердичів", "Звягель", "Коростень", "Коростишів", "Малин"],
    "Закарпатська": ["Ужгород", "Берегове", "Мукачево", "Рахів", "Тячів", "Хуст", "Виноградів", "Свалява"],
    "Запорізька": ["Запоріжжя", "Бердянськ", "Василівка", "Мелітополь", "Пологи", "Енергодар", "Токмак"],
    "Івано-Франківська": ["Івано-Франківськ", "Калуш", "Коломия", "Косів", "Надвірна", "Яремче", "Верховина", "селище Верховина", "Поляниця"],
    "Київська": ["Київ", "Біла Церква", "Бориспіль", "Бровари", "Буча", "Вишгород", "Обухів", "Фастів", "Ірпінь", "Васильків", "Вишневе", "Гостомель", "селище Гостомель"],
    "Кіровоградська": ["Кропивницький", "Новоукраїнка", "Олександрія", "Світловодськ", "Знам'янка", "Голованівськ"],
    "Луганська": ["Луганськ", "Алчевськ", "Довжанськ", "Ровеньки", "Сватове", "Старобільськ", "Сіверськодонецьк", "Щастя", "Лисичанськ"],
    "Львівська": ["Львів", "Дрогобич", "Золочів", "Самбір", "Стрий", "Шептицький", "Червоноград", "Яворів", "Трускавець", "Борислав", "Славське"],
    "Миколаївська": ["Миколаїв", "Баштанка", "Вознесенськ", "Первомайськ", "Южноукраїнськ", "Очаків"],
    "Одеська": ["Одеса", "Березівка", "Білгород-Дністровський", "Болград", "Ізмаїл", "Подільськ", "Роздільна", "Чорноморськ", "Затока"],
    "Полтавська": ["Полтава", "Кременчук", "Лубни", "Миргород", "Горішні Плавні", "Гадяч"],
    "Рівненська": ["Рівне", "Вараш", "Дубно", "Сарни", "Костопіль", "Здолбунів"],
    "Сумська": ["Суми", "Конотоп", "Охтирка", "Ромни", "Шостка", "Глухів", "Лебедин"],
    "Тернопільська": ["Тернопіль", "Кременець", "Чортків", "Бережани", "Бучач", "Заліщики"],
    "Харківська": ["Харків", "Богодухів", "Ізюм", "Красноград", "Куп'янськ", "Лозова", "Чугуїв", "Балаклія"],
    "Херсонська": ["Херсон", "Берислав", "Генічеськ", "Каховка", "Нова Каховка", "Скадовськ", "Олешки"],
    "Хмельницька": ["Хмельницький", "Кам'янець-Подільський", "Шепетівка", "Нетішин", "Славута", "Старокостянтинів"],
    "Черкаська": ["Черкаси", "Звенигородка", "Золотоноша", "Умань", "Сміла", "Канів"],
    "Чернівецька": ["Чернівці", "Вижниця", "Новодністровськ", "Хотин", "Сторожинець", "Кельменці"],
    "Чернігівська": ["Чернігів", "Корюківка", "Ніжин", "Новгород-Сіверський", "Прилуки", "Бахмач"],
    "Автономна Республіка Крим": ["Сімферополь", "Севастополь", "Євпаторія", "Бахчисарай", "Білогірськ", "Джанкой", "Керч", "Феодосія", "Ялта", "Алушта"],
}

CITY_REGION_MAP: dict[str, str] = {
    "київ": "Київська",
    "львів": "Львівська",
    "одеса": "Одеська",
    "харків": "Харківська",
    "дніпро": "Дніпропетровська",
    "вінниця": "Вінницька",
    "запоріжжя": "Запорізька",
    "івано-франківськ": "Івано-Франківська",
    "ужгород": "Закарпатська",
    "чернівці": "Чернівецька",
    "житомир": "Житомирська",
    "полтава": "Полтавська",
    "рівне": "Рівненська",
    "суми": "Сумська",
    "тернопіль": "Тернопільська",
    "херсон": "Херсонська",
    "хмельницький": "Хмельницька",
    "черкаси": "Черкаська",
    "чернігів": "Чернігівська",
    "кропивницький": "Кіровоградська",
    "миколаїв": "Миколаївська",
    "луцьк": "Волинська",
    "донецьк": "Донецька",
    "луганськ": "Луганська",
    "сімферополь": "Автономна Республіка Крим",
    "севастополь": "Автономна Республіка Крим",
}

for _reg, _settlements in REGION_SETTLEMENTS_MAP.items():
    for _s in _settlements:
        _k = re.sub(r"^(селище|село|м\.|смт)\s+", "", _s.lower()).strip()
        if _k not in CITY_REGION_MAP:
            CITY_REGION_MAP[_k] = _reg
        CITY_REGION_MAP[_s.lower()] = _reg


def normalize_region_name(raw: str | None) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"\s+область$", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+обл\.?$", "", cleaned, flags=re.IGNORECASE).strip()
    for region in UKRAINIAN_REGIONS:
        if region.lower() == cleaned.lower() or region.lower() == text.lower():
            return region
    return cleaned


def _infer_region_from_city(city: str | None) -> str:
    if not city:
        return ""
    raw = str(city).strip().lower()
    stripped = re.sub(r"^(селище|село|м\.|смт)\s+", "", raw).strip()
    return CITY_REGION_MAP.get(raw) or CITY_REGION_MAP.get(stripped) or ""


def normalize_listing_images(raw_images) -> list[str]:
    fallback = PLACEHOLDER_LISTING_IMAGE
    normalized: list[str] = []
    for image in (raw_images if isinstance(raw_images, list) else []):
        raw_url = str(image or "").strip()
        if raw_url.startswith("data:image/"):
            # Historical multipart uploads were stored as large base64 values.
            # Never serialize a truncated data URI: it cannot render and bloats
            # every catalog response. The maintenance migration moves intact
            # values from the database to configured object storage.
            continue
        url = strip(raw_url, 2048)
        if not url:
            continue
        lowered_url = url.lower()
        if legacy_demo_image_seed(url):
            normalized.append(demo_image_url(legacy_demo_image_seed(url)))
            continue
        if any(domain in lowered_url for domain in ("images.unsplash.com", "source.unsplash.com", "picsum.photos", "fastly.picsum.photos")):
            normalized.append(demo_image_url("listing"))
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme in ("http", "https") and parsed.hostname:
                normalized.append(url)
                continue
        except ValueError:
            pass
        # Anything else → placeholder
        normalized.append(fallback)
    return normalized or [fallback]


def has_legacy_data_uri_images(raw_images) -> bool:
    return any(
        isinstance(image, str) and image.strip().startswith("data:image/")
        for image in (raw_images if isinstance(raw_images, list) else [])
    )


def normalize_listing_videos(raw_videos) -> list[str]:
    normalized: list[str] = []
    for video in (raw_videos if isinstance(raw_videos, list) else []):
        url = strip(str(video), 2048)
        if not url:
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme in ("http", "https") and parsed.hostname:
                normalized.append(url)
        except ValueError:
            continue
    return list(dict.fromkeys(normalized))[:MAX_VIDEOS_PER_LISTING]


def parse_listing_request_payload() -> tuple[dict, list[str]]:
    """
    Parse listing data from multipart form or JSON.

    Media files must be uploaded through the presigned media endpoints first.
    Multipart file bodies are rejected instead of being persisted as base64.
    """
    data: dict = {}
    image_urls: list[str] = []

    if request.files:
        payload_json = request.form.get("payload", "")
        if payload_json:
            try:
                data = json.loads(payload_json)
            except json.JSONDecodeError:
                data = {}
        image_urls_json = request.form.get("image_urls", "[]")
        try:
            parsed_urls = json.loads(image_urls_json)
        except (TypeError, ValueError):
            parsed_urls = []
        if isinstance(parsed_urls, list):
            image_urls.extend(str(u).strip() for u in parsed_urls if str(u).strip())
    else:
        data = request.get_json(silent=True) or {}

    if any(getattr(upload, "filename", None) for upload in request.files.getlist("images")):
        data["_multipart_media_rejected"] = True

    return data, list(dict.fromkeys(image_urls))


def validate_listing_payload(data: dict, carried_images: list[str] | None = None) -> tuple[dict, dict]:
    title = strip(data.get("title"), 200)
    region = strip(data.get("region") or data.get("oblast") or "", 100)
    city = strip(data.get("city") or data.get("settlement") or data.get("place") or "", 100)
    if not region and city:
        region = _infer_region_from_city(city)
    if region:
        region = normalize_region_name(region)
    district = strip(data.get("district"), 100)
    prop_type = strip(data.get("propertyType") or data.get("property_type"), 50) or "квартира"
    condition = strip(data.get("conditionType") or data.get("condition_type"), 50) or "вторинка"
    description = strip(data.get("description"), 2000)
    price = pos_int(data.get("price"))
    rooms = nonneg_int(data.get("rooms"))
    area = pos_float(data.get("area"))
    floor = nonneg_int(data.get("floor")) or 1
    total_floors = pos_int(data.get("totalFloors") or data.get("total_floors")) or 1
    year_built = nonneg_int(data.get("yearBuilt") or data.get("year_built"))
    e_oselya = bool(data.get("eOselya") or data.get("e_oselya") or False)
    listing_type = strip(data.get("listingType") or data.get("listing_type") or "sale", 10).lower()
    listing_status = strip(data.get("listingStatus") or data.get("listing_status") or "active", 20).lower()
    source = strip(data.get("source", "owner"), 20).lower()
    agency_slug = strip(data.get("agencySlug") or data.get("agency_slug") or "", 80).lower() or None
    has_photo_tour = bool(data.get("hasPhotoTour") or data.get("has_photo_tour") or False)
    has_video_tour = bool(data.get("hasVideoTour") or data.get("has_video_tour") or False)
    owner_verification_requested = bool(data.get("verifiedOwner") or data.get("verified_owner") or data.get("requestOwnerVerification") or False)
    phone_verification_requested = bool(data.get("verifiedPhone") or data.get("verified_phone") or data.get("requestPhoneVerification") or False)
    verified_docs = bool(data.get("verifiedDocs") or data.get("verified_docs") or False)
    images_raw = data.get("images", [])
    videos_raw = data.get("videos", [])

    image_values: list[str] = []
    if carried_images:
        image_values.extend(str(image).strip() for image in carried_images if str(image).strip())
    if isinstance(images_raw, list):
        image_values.extend(str(image).strip() for image in images_raw if str(image).strip())
    image_values = list(dict.fromkeys(image_values))
    video_values = normalize_listing_videos(videos_raw)

    lat = data.get("latitude")
    lng = data.get("longitude")
    try:
        lat = float(lat) if lat is not None else None
        lng = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lat = lng = None

    valid_types = {"квартира", "будинок", "комерція", "земля"}
    valid_conditions = {"нова будова", "вторинка", "після ремонту", "без ремонту"}
    valid_listing_types = {"sale", "rent"}
    valid_listing_statuses = {"active", "sold", "removed"}
    valid_sources = {"owner", "agency", "agent", "seed"}

    if prop_type not in valid_types:
        prop_type = "квартира"
    if condition not in valid_conditions:
        condition = "вторинка"
    if listing_type not in valid_listing_types:
        listing_type = "sale"
    if listing_status not in valid_listing_statuses:
        listing_status = "active"
    if source not in valid_sources:
        source = "owner"
    if agency_slug and not re.match(r"^[a-z0-9-]{2,80}$", agency_slug):
        agency_slug = None

    errors = {}
    if not title:
        errors["title"] = "Назва обов'язкова"
    if not city:
        errors["city"] = "Місто обов'язкове"
    if not district:
        errors["district"] = "Район обов'язковий"
    if price is None:
        errors["price"] = "Ціна > 0"
    if rooms is None:
        errors["rooms"] = "Кімнати >= 0"
    if area is None:
        errors["area"] = "Площа > 0"
    invalid_images = []
    for image_url in image_values:
        try:
            parsed_image_url = urlsplit(image_url)
        except ValueError:
            parsed_image_url = None
        if (
            image_url.startswith("data:image/")
            or not parsed_image_url
            or parsed_image_url.scheme not in {"http", "https"}
            or not parsed_image_url.hostname
        ):
            invalid_images.append(image_url)
    if data.get("_multipart_media_rejected"):
        errors["images"] = "Завантажте фото через актуальну форму сайту."
    elif invalid_images:
        errors["images"] = "Фото повинні бути завантажені у сховище та мати коректні http(s) URL"
    elif len(image_values) > MAX_IMAGES_PER_LISTING:
        errors["images"] = f"Дозволено не більше {MAX_IMAGES_PER_LISTING} фото"
    if isinstance(videos_raw, list) and len([item for item in videos_raw if str(item).strip()]) != len(video_values):
        errors["videos"] = "Відео повинні мати коректні http(s) URL"
    if isinstance(videos_raw, list) and len(videos_raw) > MAX_VIDEOS_PER_LISTING:
        errors["videos"] = f"Дозволено не більше {MAX_VIDEOS_PER_LISTING} відео"

    payload = {
        "title": title,
        "region": region,
        "city": city,
        "district": district,
        "property_type": prop_type,
        "condition_type": condition,
        "description": description,
        "price": price,
        "rooms": rooms,
        "area": area,
        "floor": floor,
        "total_floors": total_floors,
        "year_built": year_built,
        "e_oselya": e_oselya,
        "listing_type": listing_type,
        "listing_status": listing_status,
        "source": source,
        "agency_slug": agency_slug,
        "has_photo_tour": has_photo_tour,
        "has_video_tour": bool(video_values) or has_video_tour,
        "owner_verification_requested": owner_verification_requested,
        "phone_verification_requested": phone_verification_requested,
        "verified_docs": verified_docs,
        "images_json": json.dumps(image_values[:MAX_IMAGES_PER_LISTING]),
        "videos_json": json.dumps(video_values),
        "lat": lat,
        "lng": lng,
    }
    return payload, errors

try:
    from seo_routes import (
        DEVELOPMENT_PROJECTS,
        _development_project_by_slug,
        _development_projects_for_city,
    )
except ImportError:
    try:
        from backend.seo_routes import (
            DEVELOPMENT_PROJECTS,
            _development_project_by_slug,
            _development_projects_for_city,
        )
    except ImportError:
        DEVELOPMENT_PROJECTS = []
        def _development_project_by_slug(slug: str): return None
        def _development_projects_for_city(city_name: str): return []

SEED_LISTINGS = [
    # (title, city, district, property_type, condition_type, price, rooms, area,
    #  floor, total_floors, year_built, e_oselya, images_json, description, lat, lng)
    ("Сучасна 2-кімнатна, ЖК 'Грінвіль'", "Київ", "Печерський",
     "квартира", "нова будова", 125000, 2, 68.0, 8, 24, 2021, 1,
     imgs("1560185007-c5ca9d2c014d","1502672260266-1c1ef2d93688","1493809842364-78817add7ffb"),
     "Сучасна квартира з панорамним виглядом на Дніпро. Оздоблення «комфорт плюс», підземний паркінг, консьєрж.",
     50.4422, 30.5178),

    ("Видова смарт-квартира біля метро", "Київ", "Голосіївський",
     "квартира", "після ремонту", 48000, 1, 32.0, 5, 16, 2019, 1,
     imgs("1493809842364-78817add7ffb","1484154218962-a197022b5858"),
     "Смарт-квартира з якісним ремонтом, 5 хвилин до метро. Функціональне планування для активного міського життя.",
     50.4122, 30.5122),

    ("Простора 3-к квартира для родини", "Львів", "Франківський",
     "квартира", "вторинка", 95000, 3, 85.0, 3, 9, 2008, 0,
     imgs("1484154218962-a197022b5858","1560185007-c5ca9d2c014d"),
     "Великий сімейний простір у центральному районі Львова. Поруч школа, садочок, парк. Логджія, комора.",
     49.8397, 24.0297),

    ("Затишна 1-кімнатна у новобудові", "Харків", "Слобідський",
     "квартира", "нова будова", 38000, 1, 38.5, 12, 22, 2023, 1,
     imgs("1502672260266-1c1ef2d93688","1560185007-c5ca9d2c014d"),
     "Нова квартира з чистовим оздобленням у ЖК. Закрита територія, дитячий майданчик, відеоспостереження.",
     49.9935, 36.2304),

    ("Великий пентхаус з терасою", "Одеса", "Приморський",
     "квартира", "після ремонту", 210000, 4, 140.0, 16, 16, 2018, 0,
     imgs("1512917774080-9991f1c4c750","1560185007-c5ca9d2c014d","1502672260266-1c1ef2d93688"),
     "Розкішний пентхаус з видом на Чорне море. Велика тераса, авторський дизайн, система розумного дому.",
     46.4825, 30.7233),

    ("Квартира-студія в центрі", "Дніпро", "Центральний",
     "квартира", "після ремонту", 42000, 1, 28.0, 4, 12, 2020, 1,
     imgs("1493809842364-78817add7ffb","1484154218962-a197022b5858"),
     "Сучасна студія у центрі Дніпра. Ідеально для інвестиції або молодих спеціалістів.",
     48.4647, 35.0462),

    ("Приватний будинок з ділянкою", "Київ", "Дарницький",
     "будинок", "після ремонту", 185000, 5, 180.0, 2, 2, 2015, 0,
     imgs("1523217582562-09d0def993a6","1545324418-cc1a3fa10c00","1570129477492-45c003edd2be"),
     "Двоповерховий будинок 8 соток. Підвал, гараж, літня кухня. Тихе місце поруч з транспортом.",
     50.4102, 30.6578),

    ("Офіс у центрі Львова", "Львів", "Галицький",
     "комерція", "після ремонту", 68000, 0, 75.0, 1, 5, 2010, 0,
     imgs("1497366216548-37526070297c","1449844908441-8829872d2607"),
     "Готове офісне приміщення. Окремий вхід, висока стеля 3.2 м, кімната переговорів.",
     49.8429, 24.0322),

    ("2-кімнатна біля парку", "Вінниця", "Замостянський",
     "квартира", "вторинка", 52000, 2, 58.0, 6, 9, 2005, 1,
     imgs("1484154218962-a197022b5858","1502672260266-1c1ef2d93688"),
     "Квартира після капремонту. Балкон з видом на парк, нові вікна та сантехніка.",
     49.2331, 28.4682),

    ("Будинок з садом у передмісті", "Харків", "Жовтневий",
     "будинок", "вторинка", 78000, 4, 120.0, 1, 1, 2000, 0,
     imgs("1570129477492-45c003edd2be","1545324418-cc1a3fa10c00"),
     "Одноповерховий будинок з великим садом. Ідеально для родини з дітьми, тихий район.",
     49.9453, 36.1881),

    ("Стильна 1-кімнатна для інвестиції", "Одеса", "Малиновський",
     "квартира", "нова будова", 35000, 1, 33.0, 7, 18, 2024, 1,
     imgs("1502672260266-1c1ef2d93688","1493809842364-78817add7ffb"),
     "Нова квартира у ЖК бізнес-класу. Розвинена інфраструктура, чудова локація для оренди.",
     46.4456, 30.7134),

    ("4-кімнатна преміум у центрі Києва", "Київ", "Шевченківський",
     "квартира", "після ремонту", 350000, 4, 160.0, 15, 25, 2022, 0,
     imgs("1512917774080-9991f1c4c750","1560185007-c5ca9d2c014d","1484154218962-a197022b5858"),
     "Преміум квартира з дизайнерським ремонтом. Смарт-дім, тепла підлога, консьєрж 24/7.",
     50.4420, 30.5230),
]

# Rent listings seed (listing_type = 'rent', price = monthly UAH equivalent in USD)
SEED_RENT_LISTINGS = [
    ("Оренда 2-кімнатної на Подолі", "Київ", "Подільський",
     "квартира", "після ремонту", 800, 2, 65.0, 4, 9, 2015, 0,
     imgs("1560185007-c5ca9d2c014d","1502672260266-1c1ef2d93688"),
     "Затишна квартира після ремонту. Меблі, побутова техніка, інтернет. Без посередників.",
     50.4590, 30.5226),

    ("Оренда студії біля метро Лівобережна", "Київ", "Дніпровський",
     "квартира", "після ремонту", 450, 1, 28.0, 3, 14, 2020, 0,
     imgs("1493809842364-78817add7ffb","1484154218962-a197022b5858"),
     "Сучасна студія з новими меблями та технікою. 7 хвилин пішки до метро. Є кондиціонер.",
     50.4536, 30.6118),

    ("Оренда 1-кімнатної у Львові центр", "Львів", "Галицький",
     "квартира", "вторинка", 500, 1, 42.0, 2, 5, 2010, 0,
     imgs("1484154218962-a197022b5858","1560185007-c5ca9d2c014d"),
     "Квартира в центрі Львова. Меблі та техніка, інтернет. Поруч кав'ярні та транспорт.",
     49.8397, 24.0335),

    ("Оренда офісу в бізнес-центрі", "Харків", "Слобідський",
     "комерція", "після ремонту", 1200, 0, 120.0, 5, 12, 2018, 0,
     imgs("1497366216548-37526070297c","1449844908441-8829872d2607"),
     "Сучасний офіс відкритого планування. Переговорна кімната, кухня, 24/7 доступ, паркінг.",
     49.9935, 36.2304),

    ("Оренда 3-кімнатної для родини в Одесі", "Одеса", "Приморський",
     "квартира", "після ремонту", 900, 3, 88.0, 6, 9, 2012, 0,
     imgs("1512917774080-9991f1c4c750","1502672260266-1c1ef2d93688"),
     "Простора квартира біля моря. Є все необхідне, великий балкон з видом. Власник.",
     46.4825, 30.7160),

    ("Оренда будинку з ділянкою під Києвом", "Київ", "Дарницький",
     "будинок", "вторинка", 1500, 4, 150.0, 2, 2, 2005, 0,
     imgs("1523217582562-09d0def993a6","1570129477492-45c003edd2be"),
     "Будинок з великим двором та гаражем. Тихий район, зручний виїзд на трасу. Є всі комунікації.",
     50.4102, 30.6700),
]

VERIFICATION_STATES = {"unverified", "pending", "verified", "rejected"}
MODERATION_STATES = {"pending_review", "in_review", "approved", "changes_requested", "rejected"}

ACCOUNT_TYPES = {"owner", "realtor", "developer"}
DEFAULT_ACCOUNT_TYPE = "owner"

# Subscription catalog. `listing_limit = None` means unlimited.
# `audience` decides which cabinet (owner / realtor / developer) offers the plan.
SUBSCRIPTION_PLANS: dict[str, dict] = {
    "free": {
        "name": "Базовий",
        "audience": "owner",
        "price": 0,
        "listing_limit": 5,
        "duration_days": 30,
        "features": ["5 оголошень на місяць", "30 днів активності", "Стандартна позиція"],
    },
    "standard": {
        "name": "Стандарт",
        "audience": "owner",
        "price": 299,
        "listing_limit": 5,
        "duration_days": 60,
        "features": ["5 оголошень", "60 днів активності", "Виділення в пошуку", "Статистика переглядів"],
    },
    "premium": {
        "name": "Преміум",
        "audience": "owner",
        "price": 699,
        "listing_limit": 15,
        "duration_days": 90,
        "features": ["15 оголошень", "90 днів активності", "ТОП-позиція в пошуку", "Бейдж «Перевірено»", "Детальна аналітика"],
    },
    "realtor_free": {
        "name": "Ріелтор Базовий",
        "audience": "realtor",
        "price": 0,
        "listing_limit": 30,
        "duration_days": 30,
        "features": ["30 оголошень на місяць", "30 днів активності", "Профіль ріелтора"],
    },
    "realtor_start": {
        "name": "Ріелтор Старт",
        "audience": "realtor",
        "price": 799,
        "listing_limit": 50,
        "duration_days": 30,
        "features": ["50 оголошень на місяць", "Профіль ріелтора", "Виділення в пошуку", "Статистика переглядів"],
    },
    "realtor_pro": {
        "name": "Ріелтор Про",
        "audience": "realtor",
        "price": 1499,
        "listing_limit": 100,
        "duration_days": 30,
        "features": ["100 оголошень", "ТОП-позиція в пошуку", "Бейдж «Перевірено»", "Детальна аналітика", "Пріоритетна підтримка"],
    },
    "realtor_agency": {
        "name": "Агенція",
        "audience": "realtor",
        "price": 2999,
        "listing_limit": None,
        "duration_days": 30,
        "features": ["Необмежено оголошень", "Брендинг агентства", "API доступ", "CRM-інтеграція", "Верифікація агентства", "Особистий менеджер"],
    },
    "developer_free": {
        "name": "Забудовник Базовий",
        "audience": "developer",
        "price": 0,
        "listing_limit": 20,
        "duration_days": 30,
        "features": ["20 оголошень на місяць", "30 днів активності", "Профіль забудовника", "Новобудови в каталозі"],
    },
}

DEFAULT_PLAN_BY_ACCOUNT_TYPE = {"owner": "free", "realtor": "realtor_free", "developer": "developer_free"}
PAID_PLAN_IDS = {plan_id for plan_id, plan in SUBSCRIPTION_PLANS.items() if plan["price"] > 0}


def normalize_account_type(value) -> str:
    """Coerce arbitrary input to a supported account type."""
    candidate = str(value or "").strip().lower()
    return candidate if candidate in ACCOUNT_TYPES else DEFAULT_ACCOUNT_TYPE


def default_plan_for(account_type: str) -> str:
    return DEFAULT_PLAN_BY_ACCOUNT_TYPE.get(normalize_account_type(account_type), "free")


def plan_public_dict(plan_id: str) -> dict:
    plan = SUBSCRIPTION_PLANS[plan_id]
    return {
        "id": plan_id,
        "name": plan["name"],
        "audience": plan["audience"],
        "price": plan["price"],
        "currency": "UAH",
        "listing_limit": plan["listing_limit"],
        "duration_days": plan["duration_days"],
        "features": list(plan["features"]),
    }


def resolve_user_plan(row) -> tuple[str, dict]:
    """Return the effective plan id and definition for a user row.

    Falls back to the account's free plan when the stored plan is unknown or expired.
    """
    account_type = normalize_account_type(row["account_type"] if _has_key(row, "account_type") else None)
    fallback = default_plan_for(account_type)
    plan_id = str((row["plan_id"] if _has_key(row, "plan_id") else "") or "").strip()
    if plan_id not in SUBSCRIPTION_PLANS:
        plan_id = fallback

    expires_at = str((row["plan_expires_at"] if _has_key(row, "plan_expires_at") else "") or "").strip()
    if plan_id in PAID_PLAN_IDS and expires_at:
        try:
            expiry = datetime.datetime.fromisoformat(expires_at.replace(" ", "T"))
        except ValueError:
            expiry = None
        if expiry and expiry <= datetime.datetime.utcnow():
            plan_id = fallback

    return plan_id, SUBSCRIPTION_PLANS[plan_id]


def _has_key(row, key: str) -> bool:
    try:
        return key in row.keys()
    except AttributeError:
        try:
            return key in row
        except TypeError:
            return False


def listing_usage(db, user_id: int, plan: dict) -> dict:
    """Count listings that occupy a plan slot and derive the remaining quota."""
    row = db.execute(
        "SELECT COUNT(*) AS used FROM listings"
        " WHERE user_id = ? AND status IN ('draft', 'pending', 'published')",
        (user_id,),
    ).fetchone()
    used = int(row["used"] if _has_key(row, "used") else row[0])
    limit = plan["listing_limit"]
    return {
        "listings_used": used,
        "listings_limit": limit,
        "listings_remaining": None if limit is None else max(limit - used, 0),
    }


def apply_plan_to_user(db, user_id: int, plan_id: str) -> None:
    """Activate a paid plan for a user, extending an unexpired same-plan term."""
    plan = SUBSCRIPTION_PLANS[plan_id]
    row = db.execute(
        "SELECT plan_id, plan_expires_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    start = datetime.datetime.utcnow()
    if row and str(row["plan_id"] or "") == plan_id:
        current_expiry = str(row["plan_expires_at"] or "").strip()
        if current_expiry:
            try:
                parsed = datetime.datetime.fromisoformat(current_expiry.replace(" ", "T"))
                start = max(start, parsed)
            except ValueError:
                pass

    expires_at = (start + datetime.timedelta(days=plan["duration_days"])).replace(microsecond=0).isoformat(sep=" ")
    db.execute(
        "UPDATE users SET plan_id = ?, plan_expires_at = ?, account_type = ? WHERE id = ?",
        (plan_id, expires_at, plan["audience"], user_id),
    )


def verification_state_from_bool(value) -> str:
    return "verified" if bool(value) else "unverified"

def moderation_state_from_status(status: str | None) -> str:
    status = (status or "").strip().lower()
    if status == "published":
        return "approved"
    if status == "rejected":
        return "rejected"
    if status in {"draft", "pending"}:
        return "pending_review"
    return "approved"


def log_listing_event(db: sqlite3.Connection, listing_id: int, action: str, reason: str | None = None, admin_id: int | None = None):
    actor_id = admin_id if admin_id is not None else getattr(g, "user_id", None)
    db.execute(
        "INSERT INTO moderation_log (listing_id, admin_id, action, reason) VALUES (?, ?, ?, ?)",
        (listing_id, actor_id, action, reason),
    )


def log_admin_audit(
    db,
    *,
    actor_id: int,
    actor_role: str,
    action: str,
    permission: str,
    resource_type: str,
    resource_id=None,
    changed_fields=(),
) -> None:
    sensitive = {
        "password", "password_hash", "token", "authorization", "csrf_token",
        "reporter_fingerprint", "phone", "email", "message", "details",
    }
    fields = sorted({
        str(field)[:80]
        for field in changed_fields
        if str(field).lower() not in sensitive
    })[:30]
    db.execute(
        """
        INSERT INTO admin_audit_log (
            actor_id, actor_role, action, permission, resource_type,
            resource_id, metadata_json, request_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            actor_id,
            actor_role,
            str(action)[:120],
            str(permission)[:80],
            str(resource_type)[:80],
            None if resource_id is None else str(resource_id)[:120],
            json.dumps({"changed_fields": fields}, separators=(",", ":")),
            str(getattr(g, "request_id", "unknown"))[:128],
        ),
    )


# ─── Trust & safety: seller type, field history, price stats, reports ───────

def public_seller_type(account_type, account_agency_slug=None) -> str:
    """Map the *backend user account type* (never client-supplied text) to a
    public-facing seller type. Distinct from moderation/verification state —
    this only reflects who the account actually is. Uses the raw stored
    value (not normalize_account_type's owner-fallback) so a genuinely
    missing/unsupported account type surfaces as "unknown" instead of being
    silently treated as an owner."""
    raw = str(account_type or "").strip().lower()
    if raw not in ACCOUNT_TYPES:
        return "unknown"
    slug = str(account_agency_slug or "").strip()
    if raw == "developer":
        return "developer"
    if raw == "realtor":
        return "agency" if slug else "intermediary"
    return "owner"


# Only these fields are ever written to listing_change_history — kept small
# and public-safe on purpose (no internal reasons, no admin/user IDs).
SIGNIFICANT_HISTORY_FIELDS = {
    "price", "status", "listing_status", "property_type", "rooms", "area",
    "region", "city",
    "listing_verification_status",
}
HISTORY_ACTOR_TYPES = {"owner", "admin", "system"}


def log_field_change(db, listing_id: int, field_name: str, old_value, new_value, actor_type: str = "system") -> None:
    """Append a sanitized, public-safe field-change row. No-ops for
    unsupported fields or when the value did not actually change, so history
    only ever reflects real transitions going forward (never retroactive)."""
    if field_name not in SIGNIFICANT_HISTORY_FIELDS:
        return
    if actor_type not in HISTORY_ACTOR_TYPES:
        actor_type = "system"
    old_str = None if old_value is None else str(old_value)
    new_str = None if new_value is None else str(new_value)
    if old_str == new_str:
        return
    db.execute(
        "INSERT INTO listing_change_history (listing_id, field_name, old_value, new_value, actor_type) VALUES (?, ?, ?, ?, ?)",
        (listing_id, field_name, old_str, new_str, actor_type),
    )


def public_field_history(db, listing_id: int, limit: int = 50) -> list[dict]:
    limit = min(max(int(limit or 50), 1), 50)
    rows = db.execute(
        """
        SELECT field_name, old_value, new_value, actor_type, created_at
        FROM listing_change_history
        WHERE listing_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (listing_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def comparable_price_stats(db, subject_row) -> dict:
    """Median-based price benchmark against *real* comparable published
    listings only (excludes the subject itself). Requires >=3 comparables
    or reports insufficient_data with a real sample_size and null medians."""
    def _get(key, default=None):
        try:
            return subject_row[key]
        except (KeyError, IndexError, TypeError):
            return default

    subject_id = _get("id")
    city = _get("city")
    district = _get("district")
    property_type = _get("property_type")
    listing_type = _get("listing_type")
    rooms = int(_get("rooms") or 0)
    area = float(_get("area") or 0)
    price = float(_get("price") or 0)

    subject_ppsqm = round(price / area, 2) if area > 0 and price > 0 else None

    query = """
        SELECT price, area FROM listings
        WHERE status = 'published' AND listing_status = 'active'
          AND id != ? AND city = ? AND district = ? AND property_type = ? AND listing_type = ?
          AND price > 0 AND area > 0
    """
    params: list = [subject_id, city, district, property_type, listing_type]
    if rooms > 0:
        query += " AND rooms = ?"
        params.append(rooms)
    if area > 0:
        query += " AND area BETWEEN ? AND ?"
        params.extend([area * 0.8, area * 1.2])
    rows = db.execute(query, params).fetchall()
    comp_prices: list[float] = []
    comp_ppsqm: list[float] = []
    for row in rows:
        try:
            r_price = float(row["price"])
            r_area = float(row["area"])
        except (KeyError, TypeError, ValueError):
            continue
        if r_price > 0 and r_area > 0:
            comp_prices.append(r_price)
            comp_ppsqm.append(r_price / r_area)

    sample_size = len(comp_prices)
    result = {
        "status": "insufficient_data",
        "sample_size": sample_size,
        "median_price": None,
        "median_price_per_sqm": None,
        "subject_price_per_sqm": subject_ppsqm,
        "percent_diff_from_median_per_sqm": None,
    }
    if sample_size < 3:
        return result

    median_price = statistics.median(comp_prices)
    median_ppsqm = statistics.median(comp_ppsqm)
    percent_diff = None
    if subject_ppsqm is not None and median_ppsqm:
        percent_diff = round(((subject_ppsqm - median_ppsqm) / median_ppsqm) * 100, 1)

    result.update({
        "status": "ok",
        "median_price": round(median_price, 2),
        "median_price_per_sqm": round(median_ppsqm, 2),
        "percent_diff_from_median_per_sqm": percent_diff,
    })
    return result


REPORT_REASON_CODES = (
    "fraud_scam",
    "duplicate_listing",
    "misleading_price",
    "sold_or_unavailable",
    "spam",
    "other",
)


def _reporter_fingerprint(identity: str) -> str:
    """Stable, non-reversible reporter identity digest.

    The authenticated user id or anonymous client session is HMAC'd with the
    server secret. Request IP and User-Agent remain available to the rate
    limiter but are deliberately excluded here so safe retries keep working
    across mobile-network and browser changes.
    """
    material = identity.encode("utf-8")
    return hmac.new(SECRET_KEY.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _ensure_sqlite_agency_updated_at_contract(db) -> None:
    updated_at_column = next(
        (
            row
            for row in db.execute("PRAGMA table_info(agency_profiles)").fetchall()
            if row[1] == "updated_at"
        ),
        None,
    )
    if (
        updated_at_column
        and updated_at_column[3] == 1
        and updated_at_column[4] == "datetime('now')"
    ):
        return

    db.execute("DROP TABLE IF EXISTS agency_profiles_updated_at_migration")
    db.execute(
        """
        CREATE TABLE agency_profiles_updated_at_migration (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            slug                  TEXT    NOT NULL UNIQUE,
            name                  TEXT    NOT NULL,
            kind                  TEXT    NOT NULL DEFAULT 'agency',
            city                  TEXT    NOT NULL,
            specialization        TEXT    NOT NULL DEFAULT '',
            is_verified           INTEGER NOT NULL DEFAULT 0,
            status                TEXT    NOT NULL DEFAULT 'active',
            avg_response_minutes  INTEGER,
            team_size             INTEGER,
            completed_deals       INTEGER NOT NULL DEFAULT 0,
            last_verified_at      TEXT,
            revision              INTEGER NOT NULL DEFAULT 1,
            created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at            TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        INSERT INTO agency_profiles_updated_at_migration (
            id, slug, name, kind, city, specialization, is_verified, status,
            avg_response_minutes, team_size, completed_deals, last_verified_at,
            revision, created_at, updated_at
        )
        SELECT
            id, slug, name, kind, city, specialization, is_verified, status,
            avg_response_minutes, team_size, completed_deals, last_verified_at,
            revision, created_at, updated_at
        FROM agency_profiles
        """
    )
    db.execute("DROP TABLE agency_profiles")
    db.execute(
        "ALTER TABLE agency_profiles_updated_at_migration RENAME TO agency_profiles"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agency_profiles_verified"
        " ON agency_profiles(is_verified)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agency_profiles_city ON agency_profiles(city)"
    )


def init_db():
    if _is_postgres():
        _init_postgres_db()
        return
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    now_expr = db_now_expr()
    
    # print("[init_db] Creating tables...", file=sys.stderr)
    try:
        schema_sql = """
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            email           TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password        TEXT    NOT NULL,
            password_hash   TEXT,
            role            TEXT    NOT NULL DEFAULT 'user',
            account_type    TEXT    NOT NULL DEFAULT 'owner',
            plan_id         TEXT    NOT NULL DEFAULT 'free',
            plan_expires_at TEXT,
            agency_slug     TEXT,
            auth_token_version INTEGER NOT NULL DEFAULT 0,
            status          TEXT    NOT NULL DEFAULT 'active',
            created_at      TEXT    NOT NULL DEFAULT (db_now_expr())
        );

        CREATE TABLE IF NOT EXISTS listings (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title          TEXT    NOT NULL,
            region         TEXT,
            city           TEXT    NOT NULL,
            district       TEXT    NOT NULL,
            property_type  TEXT    NOT NULL DEFAULT 'квартира',
            condition_type TEXT    NOT NULL DEFAULT 'вторинка',
            price          INTEGER NOT NULL CHECK(price > 0),
            rooms          INTEGER NOT NULL CHECK(rooms >= 0),
            area           REAL    NOT NULL CHECK(area > 0),
            floor          INTEGER NOT NULL DEFAULT 1,
            total_floors   INTEGER NOT NULL DEFAULT 1,
            year_built     INTEGER,
            e_oselya       INTEGER NOT NULL DEFAULT 0,
            views          INTEGER NOT NULL DEFAULT 0,
            images         TEXT    NOT NULL DEFAULT '[]',
            videos         TEXT    NOT NULL DEFAULT '[]',
            status         TEXT    NOT NULL DEFAULT 'draft',
            listing_type   TEXT    NOT NULL DEFAULT 'sale',
            source         TEXT    NOT NULL DEFAULT 'owner',
            agency_slug    TEXT,
            listing_status TEXT    NOT NULL DEFAULT 'active',
            has_photo_tour INTEGER NOT NULL DEFAULT 0,
            has_video_tour INTEGER NOT NULL DEFAULT 0,
            listing_highlights TEXT NOT NULL DEFAULT '[]',
            capture_mode   TEXT    NOT NULL DEFAULT 'off_site',
            verified_owner INTEGER NOT NULL DEFAULT 0,
            verified_phone INTEGER NOT NULL DEFAULT 0,
            verified_docs  INTEGER NOT NULL DEFAULT 0,
            owner_verification_status TEXT NOT NULL DEFAULT 'unverified',
            phone_verification_status TEXT NOT NULL DEFAULT 'unverified',
            moderation_status TEXT NOT NULL DEFAULT 'pending_review',
            moderation_reason TEXT,
            moderation_updated_at TEXT,
            listing_verification_status TEXT NOT NULL DEFAULT 'unverified',
            last_confirmed_at TEXT,
            freshness_reminder_sent_at TEXT,
            published_at  TEXT,
            latitude       REAL,
            longitude      REAL,
            description    TEXT    NOT NULL DEFAULT '',
            created_at     TEXT    NOT NULL DEFAULT (db_now_expr())
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_name  TEXT    NOT NULL,
            rating     INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment    TEXT    NOT NULL,
            created_at TEXT    NOT NULL DEFAULT (db_now_expr())
        );

        CREATE INDEX IF NOT EXISTS idx_listings_city      ON listings(city);
        CREATE INDEX IF NOT EXISTS idx_listings_region    ON listings(region);
        CREATE INDEX IF NOT EXISTS idx_listings_status_created_at ON listings(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_status_city ON listings(status, city);
        CREATE INDEX IF NOT EXISTS idx_listings_status_region ON listings(status, region);
        CREATE INDEX IF NOT EXISTS idx_listings_status_listing_type ON listings(status, listing_type);
        CREATE INDEX IF NOT EXISTS idx_listings_status_agency_slug ON listings(status, agency_slug);
        CREATE INDEX IF NOT EXISTS idx_listings_agency_created_at ON listings(agency_slug, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_status_published_at ON listings(status, published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_price     ON listings(price);
        CREATE INDEX IF NOT EXISTS idx_listings_user_id   ON listings(user_id);
        CREATE INDEX IF NOT EXISTS idx_listings_type      ON listings(property_type);
        CREATE INDEX IF NOT EXISTS idx_reviews_listing_id ON reviews(listing_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_listing_created_at ON reviews(listing_id, created_at DESC);
        
        CREATE TABLE IF NOT EXISTS listing_images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            image_url  TEXT    NOT NULL,
            'order'    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        
        CREATE TABLE IF NOT EXISTS moderation_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            admin_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action     TEXT    NOT NULL,
            reason     TEXT,
            created_at TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        
        CREATE INDEX IF NOT EXISTS idx_listing_images ON listing_images(listing_id);
        CREATE INDEX IF NOT EXISTS idx_moderation_log ON moderation_log(listing_id);
        CREATE INDEX IF NOT EXISTS idx_moderation_log_created_at ON moderation_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_status_e_oselya ON listings(status, e_oselya);
        CREATE INDEX IF NOT EXISTS idx_listings_status_listing_status ON listings(status, listing_status);
        CREATE INDEX IF NOT EXISTS idx_listings_status_verified ON listings(status, verified_owner, verified_phone, verified_docs);
        CREATE TABLE IF NOT EXISTS listing_alerts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
            email        TEXT    NOT NULL,
            name         TEXT,
            filters      TEXT    NOT NULL,
            is_active    INTEGER NOT NULL DEFAULT 1,
            last_sent_at TEXT,
            last_sent_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
            last_scanned_at TEXT,
            last_scanned_listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
            email_normalized TEXT,
            subscription_key TEXT UNIQUE,
            verification_token_hash TEXT,
            verification_expires_at TEXT,
            verification_sent_at TEXT,
            verified_at TEXT,
            unsubscribe_version INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE TABLE IF NOT EXISTS alert_delivery_receipts (
            alert_id INTEGER NOT NULL REFERENCES listing_alerts(id) ON DELETE CASCADE,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            channel TEXT NOT NULL,
            event_key TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (db_now_expr()),
            PRIMARY KEY (alert_id, listing_id, channel, event_key)
        );
        CREATE INDEX IF NOT EXISTS idx_listing_alerts_user ON listing_alerts(user_id);
        CREATE INDEX IF NOT EXISTS idx_listing_alerts_email ON listing_alerts(email);
        CREATE INDEX IF NOT EXISTS idx_listing_alerts_last_sent ON listing_alerts(last_sent_at);
        CREATE INDEX IF NOT EXISTS idx_alert_delivery_receipts_created ON alert_delivery_receipts(created_at);

        CREATE TABLE IF NOT EXISTS push_devices (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token        TEXT    NOT NULL UNIQUE,
            platform     TEXT    NOT NULL,
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT    NOT NULL DEFAULT (db_now_expr()),
            last_seen_at TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_push_devices_user ON push_devices(user_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_push_devices_last_seen ON push_devices(last_seen_at);

        CREATE TABLE IF NOT EXISTS user_favorites (
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (db_now_expr()),
            PRIMARY KEY (user_id, listing_id)
        );
        CREATE INDEX IF NOT EXISTS idx_user_favorites_listing ON user_favorites(listing_id);
        CREATE INDEX IF NOT EXISTS idx_user_favorites_created ON user_favorites(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS alert_dispatch_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trigger_type TEXT    NOT NULL,
            dry_run      INTEGER NOT NULL DEFAULT 0,
            listing_id   INTEGER REFERENCES listings(id) ON DELETE SET NULL,
            checked      INTEGER NOT NULL DEFAULT 0,
            matched      INTEGER NOT NULL DEFAULT 0,
            email_sent   INTEGER NOT NULL DEFAULT 0,
            push_sent    INTEGER NOT NULL DEFAULT 0,
            success      INTEGER NOT NULL DEFAULT 0,
            error_text   TEXT,
            started_at   TEXT    NOT NULL DEFAULT (db_now_expr()),
            finished_at  TEXT,
            duration_ms  INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_alert_dispatch_runs_started_at ON alert_dispatch_runs(started_at);
        CREATE INDEX IF NOT EXISTS idx_alert_dispatch_runs_success ON alert_dispatch_runs(success);

        CREATE TABLE IF NOT EXISTS system_status_snapshots (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            generated_at        TEXT NOT NULL,
            overall_status      TEXT NOT NULL,
            snapshot_json       TEXT NOT NULL,
            refresh_duration_ms INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_system_status_snapshots_generated_at
            ON system_status_snapshots(generated_at);

        CREATE TABLE IF NOT EXISTS system_incidents (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint         TEXT NOT NULL UNIQUE,
            component           TEXT NOT NULL,
            severity            TEXT NOT NULL,
            summary             TEXT NOT NULL,
            first_seen_at       TEXT NOT NULL,
            last_seen_at        TEXT NOT NULL,
            resolved_at         TEXT,
            status              TEXT NOT NULL DEFAULT 'open',
            notified_at         TEXT,
            notification_result TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_system_incidents_open
            ON system_incidents(status, component);

        CREATE TABLE IF NOT EXISTS lead_funnel_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id   INTEGER REFERENCES listings(id) ON DELETE SET NULL,
            event        TEXT    NOT NULL,
            intent       TEXT    NOT NULL,
            source       TEXT    NOT NULL,
            listing_type TEXT,
            price        INTEGER,
            session_id   TEXT,
            created_at   TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_created ON lead_funnel_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_created_source_event ON lead_funnel_events(created_at, source, event);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_source ON lead_funnel_events(source);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_source_created ON lead_funnel_events(source, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_event ON lead_funnel_events(event);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_listing ON lead_funnel_events(listing_id);

        CREATE TABLE IF NOT EXISTS lead_funnel_daily_metrics (
            day TEXT NOT NULL,
            source TEXT NOT NULL,
            listing_type TEXT NOT NULL,
            event TEXT NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, source, listing_type, event)
        );
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_daily_metrics_day ON lead_funnel_daily_metrics(day);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_daily_metrics_source_day ON lead_funnel_daily_metrics(source, day);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_daily_metrics_type_day ON lead_funnel_daily_metrics(listing_type, day);

        CREATE TABLE IF NOT EXISTS lead_funnel_listing_metrics (
            day TEXT NOT NULL,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            event TEXT NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (day, listing_id, event)
        );
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_listing_metrics_day ON lead_funnel_listing_metrics(day);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_listing_metrics_listing ON lead_funnel_listing_metrics(listing_id);

        CREATE TABLE IF NOT EXISTS lead_funnel_session_rollups (
            session_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            route_applies INTEGER NOT NULL DEFAULT 0,
            first_route_at TEXT,
            submit_at TEXT,
            last_event_at TEXT NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_session_rollups_source ON lead_funnel_session_rollups(source);
        CREATE INDEX IF NOT EXISTS idx_lead_funnel_session_rollups_first_route ON lead_funnel_session_rollups(first_route_at);

        CREATE TABLE IF NOT EXISTS lead_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_type TEXT NOT NULL,
            source TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            bank TEXT,
            project_slug TEXT,
            project_name TEXT,
            city TEXT,
            district TEXT,
            amount INTEGER,
            down_payment INTEGER,
            years INTEGER,
            e_oselya INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            listing_id INTEGER REFERENCES listings(id) ON DELETE SET NULL,
            session_id TEXT,
            requester_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            preferred_channel TEXT NOT NULL DEFAULT 'phone',
            status TEXT NOT NULL DEFAULT 'new',
            response_message TEXT,
            responded_at TEXT,
            created_at TEXT NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_lead_requests_created_at ON lead_requests(created_at);
        CREATE INDEX IF NOT EXISTS idx_lead_requests_type_created ON lead_requests(lead_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_lead_requests_project_slug ON lead_requests(project_slug);
        CREATE INDEX IF NOT EXISTS idx_lead_requests_session ON lead_requests(session_id);

        CREATE TABLE IF NOT EXISTS client_observability_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type   TEXT    NOT NULL,
            metric_name  TEXT,
            metric_value REAL,
            rating       TEXT,
            message      TEXT,
            stack        TEXT,
            source       TEXT,
            page_url     TEXT,
            session_id   TEXT,
            user_agent   TEXT,
            payload_json TEXT,
            created_at   TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_client_observability_created ON client_observability_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_client_observability_type_created ON client_observability_events(event_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_client_observability_metric_created ON client_observability_events(metric_name, created_at DESC);

        CREATE TABLE IF NOT EXISTS listing_city_summary (
            city TEXT PRIMARY KEY,
            published_count INTEGER NOT NULL DEFAULT 0,
            price_sum INTEGER NOT NULL DEFAULT 0,
            avg_price INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_listing_city_summary_count ON listing_city_summary(published_count DESC, city ASC);

        CREATE TABLE IF NOT EXISTS user_growth_daily (
            day TEXT PRIMARY KEY,
            user_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_user_growth_daily_day ON user_growth_daily(day);

        CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);

        CREATE TABLE IF NOT EXISTS agency_profiles (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            slug                  TEXT    NOT NULL UNIQUE,
            name                  TEXT    NOT NULL,
            kind                  TEXT    NOT NULL DEFAULT 'agency',
            city                  TEXT    NOT NULL,
            specialization        TEXT    NOT NULL DEFAULT '',
            is_verified           INTEGER NOT NULL DEFAULT 0,
            status                TEXT    NOT NULL DEFAULT 'active',
            avg_response_minutes  INTEGER,
            team_size             INTEGER,
            completed_deals       INTEGER NOT NULL DEFAULT 0,
            last_verified_at      TEXT,
            revision              INTEGER NOT NULL DEFAULT 1,
            created_at            TEXT    NOT NULL DEFAULT (db_now_expr()),
            updated_at            TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_agency_profiles_verified ON agency_profiles(is_verified);
        CREATE INDEX IF NOT EXISTS idx_agency_profiles_city ON agency_profiles(city);

        CREATE TABLE IF NOT EXISTS premium_orders (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   TEXT    NOT NULL UNIQUE,
            plan_id    TEXT    NOT NULL,
            amount     REAL,
            currency   TEXT    NOT NULL DEFAULT 'UAH',
            status     TEXT    NOT NULL DEFAULT 'pending',
            user_id    INTEGER,
            environment TEXT   NOT NULL DEFAULT 'disabled',
            provider_status TEXT,
            provider_payment_id TEXT,
            processed_at TEXT,
            paid_at TEXT,
            previous_plan_id TEXT,
            previous_plan_expires_at TEXT,
            activated_plan_expires_at TEXT,
            entitlement_chain_id TEXT,
            created_at TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_premium_orders_status ON premium_orders(status);

        CREATE TABLE IF NOT EXISTS listing_reports (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id           INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            reporter_user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reporter_fingerprint TEXT    NOT NULL,
            reason_code          TEXT    NOT NULL,
            details              TEXT    NOT NULL,
            status               TEXT    NOT NULL DEFAULT 'pending',
            idempotency_key      TEXT    NOT NULL UNIQUE,
            created_at           TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_listing_reports_listing ON listing_reports(listing_id);
        CREATE INDEX IF NOT EXISTS idx_listing_reports_status ON listing_reports(status);
        CREATE INDEX IF NOT EXISTS idx_listing_reports_dedupe ON listing_reports(listing_id, reporter_fingerprint, reason_code, created_at);

        CREATE TABLE IF NOT EXISTS listing_change_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            field_name TEXT    NOT NULL,
            old_value  TEXT,
            new_value  TEXT,
            actor_type TEXT    NOT NULL DEFAULT 'system',
            created_at TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_listing_change_history_listing ON listing_change_history(listing_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
            actor_role    TEXT NOT NULL,
            action        TEXT NOT NULL,
            permission    TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id   TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            request_id    TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON admin_audit_log(actor_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_admin_audit_resource ON admin_audit_log(resource_type, resource_id, created_at DESC);
    """
        schema_sql = schema_sql.replace("db_now_expr()", now_expr)
        db.executescript(schema_sql)
    except Exception as e:
        print(f"[init_db] CREATE TABLE error: {e}")
        raise
    
    # print("[init_db] Tables created OK")

    # Backward-compatible migration for existing databases.
    listing_columns = {
        row[1] for row in db.execute("PRAGMA table_info(listings)").fetchall()
    }
    if "region" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN region TEXT")
    if "source" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN source TEXT NOT NULL DEFAULT 'owner'")
    if "agency_slug" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN agency_slug TEXT")
    if "verified_owner" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN verified_owner INTEGER NOT NULL DEFAULT 0")
    if "verified_phone" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN verified_phone INTEGER NOT NULL DEFAULT 0")
    if "verified_docs" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN verified_docs INTEGER NOT NULL DEFAULT 0")
    if "owner_verification_status" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN owner_verification_status TEXT NOT NULL DEFAULT 'unverified'")
    if "phone_verification_status" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN phone_verification_status TEXT NOT NULL DEFAULT 'unverified'")
    if "moderation_status" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN moderation_status TEXT NOT NULL DEFAULT 'pending_review'")
    if "moderation_reason" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN moderation_reason TEXT")
    if "moderation_updated_at" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN moderation_updated_at TEXT")
    if "listing_verification_status" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN listing_verification_status TEXT NOT NULL DEFAULT 'unverified'")
    if "last_confirmed_at" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN last_confirmed_at TEXT")
    if "freshness_reminder_sent_at" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN freshness_reminder_sent_at TEXT")
    if "videos" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN videos TEXT NOT NULL DEFAULT '[]'")
    if "published_at" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN published_at TEXT")
    if "listing_type" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'sale'")
    if "listing_status" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN listing_status TEXT NOT NULL DEFAULT 'active'")
    if "has_photo_tour" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN has_photo_tour INTEGER NOT NULL DEFAULT 0")
    if "has_video_tour" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN has_video_tour INTEGER NOT NULL DEFAULT 0")
    if "listing_highlights" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN listing_highlights TEXT NOT NULL DEFAULT '[]'")
    if "capture_mode" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN capture_mode TEXT NOT NULL DEFAULT 'off_site'")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_agency_slug ON listings(agency_slug)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_status_created_at ON listings(status, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_status_city ON listings(status, city)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_status_listing_type ON listings(status, listing_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_status_agency_slug ON listings(status, agency_slug)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_agency_created_at ON listings(agency_slug, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_listings_status_published_at ON listings(status, published_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_reviews_listing_created_at ON reviews(listing_id, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_moderation_log_created_at ON moderation_log(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lead_funnel_source_created ON lead_funnel_events(source, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lead_funnel_created_source_event ON lead_funnel_events(created_at, source, event)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_client_observability_type_created ON client_observability_events(event_type, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_client_observability_metric_created ON client_observability_events(metric_name, created_at DESC)")

    # Users table migrations for email/phone verification
    user_columns = {
        row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email_verified" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0")
    if "email_verify_token" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN email_verify_token TEXT")
    if "email_verify_expires" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN email_verify_expires TEXT")
    if "phone" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    if "phone_verify_code" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN phone_verify_code TEXT")
    if "phone_verify_expires" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN phone_verify_expires TEXT")
    if "phone_verified" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN phone_verified INTEGER NOT NULL DEFAULT 0")
    if "account_type" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN account_type TEXT NOT NULL DEFAULT 'owner'")
    if "plan_id" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN plan_id TEXT NOT NULL DEFAULT 'free'")
    if "plan_expires_at" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN plan_expires_at TEXT")
    if "agency_slug" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN agency_slug TEXT")
    if "password_reset_token_hash" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN password_reset_token_hash TEXT")
    if "password_reset_expires" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN password_reset_expires TEXT")
    if "auth_token_version" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN auth_token_version INTEGER NOT NULL DEFAULT 0")
    db.execute(
        "UPDATE users SET account_type = 'owner' WHERE account_type IS NULL OR account_type NOT IN ('owner', 'realtor', 'developer')"
    )
    db.execute(
        "UPDATE users SET plan_id = CASE WHEN account_type = 'realtor' THEN 'realtor_free'"
        " WHEN account_type = 'developer' THEN 'developer_free' ELSE 'free' END"
        " WHERE plan_id IS NULL OR plan_id = ''"
    )

    premium_order_columns = {
        row[1] for row in db.execute("PRAGMA table_info(premium_orders)").fetchall()
    }
    if "environment" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN environment TEXT")
    if "provider_status" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN provider_status TEXT")
    if "provider_payment_id" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN provider_payment_id TEXT")
    if "processed_at" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN processed_at TEXT")
    if "paid_at" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN paid_at TEXT")
    if "previous_plan_id" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN previous_plan_id TEXT")
    if "previous_plan_expires_at" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN previous_plan_expires_at TEXT")
    if "activated_plan_expires_at" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN activated_plan_expires_at TEXT")
    if "entitlement_chain_id" not in premium_order_columns:
        db.execute("ALTER TABLE premium_orders ADD COLUMN entitlement_chain_id TEXT")
    db.execute(
        "UPDATE premium_orders SET environment = ?"
        " WHERE environment IS NULL OR environment = ''"
        " OR (environment = 'disabled' AND status IN ('pending', 'success', 'sandbox'))",
        (_legacy_liqpay_environment(),),
    )

    listing_alert_columns = {
        row[1] for row in db.execute("PRAGMA table_info(listing_alerts)").fetchall()
    }
    if "last_sent_listing_id" not in listing_alert_columns:
        db.execute(
            "ALTER TABLE listing_alerts ADD COLUMN last_sent_listing_id INTEGER"
            " REFERENCES listings(id) ON DELETE SET NULL"
        )
    if "last_scanned_at" not in listing_alert_columns:
        db.execute("ALTER TABLE listing_alerts ADD COLUMN last_scanned_at TEXT")
    if "last_scanned_listing_id" not in listing_alert_columns:
        db.execute(
            "ALTER TABLE listing_alerts ADD COLUMN last_scanned_listing_id INTEGER"
            " REFERENCES listings(id) ON DELETE SET NULL"
        )
    alert_column_definitions = {
        "email_normalized": "TEXT",
        "subscription_key": "TEXT",
        "verification_token_hash": "TEXT",
        "verification_expires_at": "TEXT",
        "verification_sent_at": "TEXT",
        "verified_at": "TEXT",
        "unsubscribe_version": "INTEGER NOT NULL DEFAULT 0",
    }
    for column, definition in alert_column_definitions.items():
        if column not in listing_alert_columns:
            db.execute(f"ALTER TABLE listing_alerts ADD COLUMN {column} {definition}")
    db.execute(
        "UPDATE listing_alerts SET email_normalized = LOWER(TRIM(email))"
        " WHERE email_normalized IS NULL"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_listing_alerts_subscription_key"
        " ON listing_alerts(subscription_key)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_alerts_email_state"
        " ON listing_alerts(email_normalized, is_active)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_listing_alerts_verification_token"
        " ON listing_alerts(verification_token_hash)"
    )

    lead_request_columns = {
        row[1] for row in db.execute("PRAGMA table_info(lead_requests)").fetchall()
    }
    if "requester_user_id" not in lead_request_columns:
        db.execute("ALTER TABLE lead_requests ADD COLUMN requester_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "preferred_channel" not in lead_request_columns:
        db.execute("ALTER TABLE lead_requests ADD COLUMN preferred_channel TEXT NOT NULL DEFAULT 'phone'")
    if "status" not in lead_request_columns:
        db.execute("ALTER TABLE lead_requests ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")
    if "response_message" not in lead_request_columns:
        db.execute("ALTER TABLE lead_requests ADD COLUMN response_message TEXT")
    if "responded_at" not in lead_request_columns:
        db.execute("ALTER TABLE lead_requests ADD COLUMN responded_at TEXT")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lead_requests_listing_status ON lead_requests(listing_id, status, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_lead_requests_requester ON lead_requests(requester_user_id, created_at DESC)")
    db.execute(
        """
        UPDATE premium_orders
        SET provider_status = status,
            status = 'paid',
            paid_at = COALESCE(paid_at, created_at),
            processed_at = COALESCE(processed_at, created_at),
            previous_plan_id = COALESCE(
                previous_plan_id,
                CASE
                    WHEN plan_id LIKE 'realtor_%' THEN 'realtor_free'
                    WHEN plan_id LIKE 'developer_%' THEN 'developer_free'
                    ELSE 'free'
                END
            ),
            entitlement_chain_id = COALESCE(entitlement_chain_id, order_id)
        WHERE status IN ('success', 'sandbox')
        """
    )
    db.execute(
        "UPDATE premium_orders SET entitlement_chain_id = order_id"
        " WHERE status = 'paid' AND entitlement_chain_id IS NULL"
    )

    agency_columns = {
        row[1] for row in db.execute("PRAGMA table_info(agency_profiles)").fetchall()
    }
    if "team_size" not in agency_columns:
        db.execute("ALTER TABLE agency_profiles ADD COLUMN team_size INTEGER")
    if "completed_deals" not in agency_columns:
        db.execute("ALTER TABLE agency_profiles ADD COLUMN completed_deals INTEGER NOT NULL DEFAULT 0")
    if "status" not in agency_columns:
        db.execute("ALTER TABLE agency_profiles ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
    if "revision" not in agency_columns:
        db.execute("ALTER TABLE agency_profiles ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
    if "updated_at" not in agency_columns:
        db.execute("ALTER TABLE agency_profiles ADD COLUMN updated_at TEXT")
    db.execute(
        f"""
        UPDATE agency_profiles
        SET completed_deals = COALESCE(completed_deals, 0),
            status = CASE WHEN status IN ('active', 'suspended') THEN status ELSE 'active' END,
            revision = CASE WHEN revision > 0 THEN revision ELSE 1 END,
            updated_at = COALESCE(updated_at, created_at, {now_expr})
        """
    )
    _ensure_sqlite_agency_updated_at_contract(db)
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_agency_profiles_kind_status"
        " ON agency_profiles(kind, status)"
    )

    db.execute("UPDATE listings SET source = COALESCE(NULLIF(source, ''), 'owner')")
    db.execute("UPDATE listings SET listing_status = COALESCE(NULLIF(listing_status, ''), 'active')")
    db.execute("UPDATE listings SET agency_slug = NULLIF(TRIM(COALESCE(agency_slug, '')), '')")
    db.execute(
        """
        UPDATE listings
        SET owner_verification_status = CASE
                WHEN verified_owner = 1 THEN 'verified'
                WHEN COALESCE(NULLIF(owner_verification_status, ''), '') = '' THEN 'unverified'
                ELSE owner_verification_status
            END,
            phone_verification_status = CASE
                WHEN verified_phone = 1 THEN 'verified'
                WHEN COALESCE(NULLIF(phone_verification_status, ''), '') = '' THEN 'unverified'
                ELSE phone_verification_status
            END,
            moderation_status = CASE
                WHEN COALESCE(NULLIF(moderation_status, ''), '') != '' THEN moderation_status
                WHEN status = 'published' THEN 'approved'
                WHEN status = 'rejected' THEN 'rejected'
                WHEN status IN ('draft', 'pending') THEN 'pending_review'
                ELSE 'approved'
            END,
            moderation_updated_at = COALESCE(moderation_updated_at, published_at, created_at),
            listing_verification_status = CASE
                WHEN listing_verification_status IN ('unverified', 'pending', 'verified', 'rejected') THEN listing_verification_status
                ELSE 'unverified'
            END
        """
    )
    _refresh_listing_city_summary(db)
    _refresh_user_growth_summary(db)
    _bootstrap_admin_user(db)
    db.commit()

    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        demo_pw = bcrypt.hashpw(b"demo1234", bcrypt.gensalt(rounds=12)).decode()
        cur = db.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            ("UA Homes Demo", "demo@ua-dim.com", demo_pw),
        )
        demo_id = cur.lastrowid
        db.executemany(
            f"""INSERT INTO listings
               (user_id,title,city,district,property_type,condition_type,price,rooms,area,
                floor,total_floors,year_built,e_oselya,images,description,latitude,longitude,
                status,published_at,verified_owner,verified_phone,verified_docs,source,listing_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'published',{now_expr},1,1,1,'seed','sale')""",
            [(demo_id, *row) for row in SEED_LISTINGS],
        )
        db.executemany(
            f"""INSERT INTO listings
               (user_id,title,city,district,property_type,condition_type,price,rooms,area,
                floor,total_floors,year_built,e_oselya,images,description,latitude,longitude,
                status,published_at,verified_owner,verified_phone,verified_docs,source,listing_type)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'published',{now_expr},1,1,1,'seed','rent')""",
            [(demo_id, *row) for row in SEED_RENT_LISTINGS],
        )
        db.commit()

    if db.execute("SELECT COUNT(*) FROM agency_profiles").fetchone()[0] == 0:
        db.executemany(
            f"""
            INSERT INTO agency_profiles
            (slug, name, kind, city, specialization, is_verified, avg_response_minutes, team_size, completed_deals, last_verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {now_expr})
            """,
            [
                ("capital-alliance", "Capital Alliance", "agency", "Київ", "Преміум квартири та будинки", 1, 32, 24, 460),
                ("lviv-home-experts", "Lviv Home Experts", "agency", "Львів", "Сімейні квартири + єОселя", 1, 41, 16, 280),
                ("dnipro-urban-group", "Dnipro Urban Group", "developer", "Дніпро", "Новобудови комфорт+ класу", 1, 55, 32, 520),
                ("odesa-coast-build", "Odesa Coast Build", "developer", "Одеса", "Будинки та апартаменти біля моря", 1, 49, 18, 340),
            ],
        )
        db.commit()

    # Ensure seed/demo rows are publicly visible after migrations.
    db.execute(
        """
        UPDATE listings
        SET status = 'published',
            published_at = COALESCE(published_at, created_at),
            verified_owner = 1,
            verified_phone = 1,
            verified_docs = 1,
            owner_verification_status = 'verified',
            phone_verification_status = 'verified',
            moderation_status = 'approved',
            moderation_reason = NULL,
            moderation_updated_at = COALESCE(moderation_updated_at, published_at, created_at),
            source = COALESCE(NULLIF(source, ''), 'seed'),
            agency_slug = CASE
                WHEN city = 'Київ' THEN 'capital-alliance'
                WHEN city = 'Львів' THEN 'lviv-home-experts'
                WHEN city = 'Дніпро' THEN 'dnipro-urban-group'
                WHEN city = 'Одеса' THEN 'odesa-coast-build'
                ELSE agency_slug
            END,
            listing_status = CASE
                WHEN id % 4 = 0 THEN 'sold'
                WHEN id % 5 = 0 THEN 'removed'
                ELSE 'active'
            END,
            has_photo_tour = CASE WHEN id % 3 = 0 THEN 1 ELSE 0 END,
            has_video_tour = CASE WHEN id % 4 = 0 THEN 1 ELSE 0 END
        WHERE user_id IN (SELECT id FROM users WHERE email = ?)
        """,
        ("demo@ua-dim.com",),
    )
    db.execute(
        """
        UPDATE agency_profiles
        SET team_size = COALESCE(team_size, 4),
            completed_deals = COALESCE(completed_deals, 0)
        """
    )
    if (
        db.execute("SELECT COUNT(*) FROM lead_funnel_events").fetchone()[0]
        and db.execute("SELECT COUNT(*) FROM lead_funnel_daily_metrics").fetchone()[0] == 0
    ):
        _refresh_lead_funnel_summaries(db)
    db.commit()

    db.close()

    # FTS5 virtual table for full-text search.
    # Done in a fresh connection AFTER all schema migrations and data updates are
    # committed, so FTS triggers won't fire during the migration UPDATEs above.
    try:
        fts_conn = sqlite3.connect(DB_PATH)
        fts_conn.execute("PRAGMA journal_mode=WAL")
        fts_conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS listings_fts USING fts5(
                title, city, district, description,
                content='listings', content_rowid='id'
            );
            CREATE TRIGGER IF NOT EXISTS listings_fts_insert AFTER INSERT ON listings BEGIN
              INSERT INTO listings_fts(rowid, title, city, district, description)
                VALUES (new.id, new.title, new.city, new.district, new.description);
            END;
            CREATE TRIGGER IF NOT EXISTS listings_fts_update AFTER UPDATE ON listings BEGIN
              INSERT INTO listings_fts(listings_fts, rowid, title, city, district, description)
                VALUES ('delete', old.id, old.title, old.city, old.district, old.description);
              INSERT INTO listings_fts(rowid, title, city, district, description)
                VALUES (new.id, new.title, new.city, new.district, new.description);
            END;
            CREATE TRIGGER IF NOT EXISTS listings_fts_delete AFTER DELETE ON listings BEGIN
              INSERT INTO listings_fts(listings_fts, rowid, title, city, district, description)
                VALUES ('delete', old.id, old.title, old.city, old.district, old.description);
            END;
        """)
        # Rebuild the full FTS index from scratch to stay consistent.
        fts_conn.execute("INSERT INTO listings_fts(listings_fts) VALUES ('rebuild')")
        fts_conn.commit()
        fts_conn.close()
    except Exception as _fts_err:
        # FTS unavailable — app will fall back to LIKE search.
        import sys
        print(f"[init_db] FTS5 setup skipped: {_fts_err}", file=sys.stderr)


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def make_token(user_id: int, email: str, token_version: int = 0) -> str:
    now = legacy_utc_now()
    payload = {
        "sub": str(user_id),
        "email": email,
        "ver": int(token_version or 0),
        "exp": now + datetime.timedelta(hours=JWT_EXP_H),
        "iat": now,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGO])


def token_matches_user_version(payload: dict, user_row) -> bool:
    try:
        return int(payload.get("ver", 0)) == int(user_row["auth_token_version"] or 0)
    except (KeyError, TypeError, ValueError):
        return False


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Токен відсутній або невалідний"), 401
        token = auth[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify(error="Сесія закінчилась — увійдіть знову"), 401
        except jwt.PyJWTError:
            return jsonify(error="Невалідний токен"), 401
        user_id = int(payload["sub"])
        db = get_db()
        user_row = db.execute(
            "SELECT id, email, auth_token_version, status FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if (
            not user_row
            or user_row["status"] != "active"
            or not token_matches_user_version(payload, user_row)
        ):
            return jsonify(error="Сесія недійсна — увійдіть знову"), 401
        g.user_id    = user_id
        g.user_email = payload["email"]
        return f(*args, **kwargs)
    return wrapper


def get_optional_actor(db) -> tuple[int | None, bool]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, False
    try:
        payload = decode_token(auth[7:])
    except (jwt.ExpiredSignatureError, jwt.PyJWTError):
        return None, False
    user_id = int(payload["sub"])
    row = db.execute(
        "SELECT role, auth_token_version, status FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row or row["status"] != "active" or not token_matches_user_version(payload, row):
        return None, False
    return user_id, row["role"] == "admin"


def _request_has_active_actor() -> bool:
    user_id, _ = get_optional_actor(get_db())
    return user_id is not None


# ─── Email / SMS helpers ─────────────────────────────────────────────────────

def _send_email(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: str,
    *,
    headers: dict[str, str] | None = None,
) -> bool:
    """Shared email dispatch via SendGrid or SMTP. Returns True on success, False otherwise."""
    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    if sg_key:
        try:
            import urllib.request as _req, json as _json
            personalization = {"to": [{"email": to_email}]}
            if headers:
                personalization["headers"] = headers
            payload = _json.dumps({
                "personalizations": [personalization],
                "from": {"email": os.environ.get("FROM_EMAIL", "noreply@ua-dim.com")},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": body_text},
                    {"type": "text/html", "value": body_html},
                ]
            }).encode()
            req = _req.Request("https://api.sendgrid.com/v3/mail/send",
                data=payload,
                headers={"Authorization": "Bearer " + sg_key, "Content-Type": "application/json"},
                method="POST")
            with _req.urlopen(req, timeout=10) as r:
                return r.status in (200, 202)
        except Exception as e:
            app.logger.error("SendGrid error: %s", e)
            return False
    elif smtp_host:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = os.environ.get("FROM_EMAIL", "noreply@ua-dim.com")
            msg["To"] = to_email
            for header_name, header_value in (headers or {}).items():
                msg[header_name] = header_value
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))
            smtp_port = int(os.environ.get("SMTP_PORT", 587))
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as srv:
                srv.starttls()
                srv.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", ""))
                srv.sendmail(msg["From"], [to_email], msg.as_string())
            return True
        except Exception as e:
            app.logger.error("SMTP error: %s", e)
            return False
    return False


def _email_provider_configured() -> bool:
    """Return True if at least one email provider (SendGrid or SMTP) is configured."""
    return bool(os.environ.get("SENDGRID_API_KEY", "") or os.environ.get("SMTP_HOST", ""))


def send_email_verify(to_email: str, token: str) -> bool:
    """Send verification email via the configured provider, or log to console in dev."""
    verify_url = f"{PUBLIC_SITE_URL or 'http://localhost:5050'}/api/auth/verify-email?token={token}"
    subject = "Підтвердіть email — UA-Dim"
    body_text = f"Перейдіть за посиланням для підтвердження: {verify_url}"
    body_html = (
        f"<p>Вітаємо в UA-Dim!</p>"
        f'<p><a href="{verify_url}">Підтвердити email</a></p>'
        f"<p>Посилання дійсне 24 години.</p>"
    )
    if _email_provider_configured():
        return _send_email(to_email, subject, body_text, body_html)
    if PUBLIC_SITE_URL:
        app.logger.warning("Email verification is not configured for production (%s)", to_email)
        return False
    app.logger.info("EMAIL VERIFY (dev) → %s | URL: %s", to_email, verify_url)
    return True


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _alert_action_token(alert_id: int, version: int, purpose: str) -> str:
    payload = f"{purpose}:{alert_id}:{version}"
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("ascii").rstrip("=")


def _parse_alert_action_token(token: str, purpose: str) -> tuple[int, int] | None:
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        token_purpose, alert_id, version, signature = decoded.split(":", 3)
        payload = f"{token_purpose}:{alert_id}:{version}"
        expected = hmac.new(
            SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if token_purpose != purpose or not secrets.compare_digest(signature, expected):
            return None
        return int(alert_id), int(version)
    except (ValueError, UnicodeError, binascii.Error):
        return None


def _alert_unsubscribe_url(alert_id: int, version: int) -> str:
    token = _alert_action_token(alert_id, version, "unsubscribe")
    base_url = (PUBLIC_SITE_URL or "http://localhost:8080").rstrip("/")
    return f"{base_url}/api/alerts/unsubscribe?token={quote(token)}"


def send_alert_verification_email(to_email: str, token: str) -> bool:
    base_url = (PUBLIC_SITE_URL or "http://localhost:8080").rstrip("/")
    verify_url = f"{base_url}/api/alerts/verify?token={quote(token)}"
    subject = "Підтвердіть сповіщення про нові оголошення — UA-Dim"
    body_text = (
        "Підтвердіть підписку на сповіщення UA-Dim:\n"
        f"{verify_url}\n\nПосилання дійсне {ALERT_VERIFY_TTL_HOURS} години."
    )
    body_html = (
        "<p>Підтвердіть підписку на сповіщення UA-Dim.</p>"
        f'<p><a href="{verify_url}">Підтвердити підписку</a></p>'
        f"<p>Посилання дійсне {ALERT_VERIFY_TTL_HOURS} години.</p>"
    )
    if _email_provider_configured():
        return _send_email(to_email, subject, body_text, body_html)
    if PUBLIC_SITE_URL:
        app.logger.warning("Alert verification email provider is not configured")
        return False
    return True


def send_sms_verify(phone: str, code: str):
    """Send SMS verification code via Twilio.

    Returns:
        True  — Twilio accepted the message.
        False — Twilio was configured but returned an error.
        None  — No Twilio credentials are configured.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token  = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_phone  = os.environ.get("TWILIO_FROM_PHONE", "")
    if account_sid and auth_token and from_phone:
        msg = f"Ваш код підтвердження UA-Dim: {code}"
        try:
            import urllib.request as _req, urllib.parse as _parse, base64 as _b64
            payload = _parse.urlencode({"To": phone, "From": from_phone, "Body": msg}).encode()
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
            creds = _b64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
            req = _req.Request(url, data=payload,
                headers={"Authorization": f"Basic {creds}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                method="POST")
            with _req.urlopen(req, timeout=10) as r:
                return r.status in (200, 201)
        except Exception as e:
            app.logger.error("Twilio error: %s", e)
            return False
    return None  # No provider configured


def send_alert_listing_email(
    to_email: str,
    alert_name: str,
    listing: dict,
    *,
    event_type: str = "new_listing",
    previous_price: int | None = None,
    unsubscribe_url: str | None = None,
) -> bool:
    listing_url = f"{PUBLIC_SITE_URL or 'http://localhost:8080'}/listing/{listing['id']}"
    is_price_change = event_type == "price_change"
    subject = (
        f"Зміна ціни за алертом «{alert_name}» — UA-Dim"
        if is_price_change
        else f"Новий об'єкт за алертом «{alert_name}» — UA-Dim"
    )
    intro = "Ціна релевантного об'єкта змінилася" if is_price_change else "Знайдено новий релевантний об'єкт"
    price_change_text = (
        f"Попередня ціна: ${int(previous_price):,}\n"
        if is_price_change and previous_price is not None
        else ""
    )
    body_text = (
        f"{intro}:\n"
        f"{listing.get('title', 'Оголошення')} — ${int(listing.get('price') or 0):,}\n"
        f"{price_change_text}"
        f"{listing.get('city', '')}, {listing.get('district', '')}\n"
        f"Переглянути: {listing_url}"
        + (f"\nВідписатися: {unsubscribe_url}" if unsubscribe_url else "")
    )
    price_change_html = (
        f'<p>Попередня ціна: <s>${int(previous_price):,}</s></p>'
        if is_price_change and previous_price is not None
        else ""
    )
    body_html = f"""<p>{intro} за вашим алертом <b>{escape(alert_name)}</b>.</p>
<p><a href="{listing_url}">{escape(listing.get("title", "Оголошення"))}</a></p>
{price_change_html}
<p><b>${int(listing.get("price") or 0):,}</b> · {escape(listing.get("city", ""))}, {escape(listing.get("district", ""))}</p>
<p>Швидкі сигнали: оновлено {listing.get("freshness_hours_ago") if listing.get("freshness_hours_ago") is not None else "—"} год тому, ризик дубля — {escape(listing.get("duplicate_risk", "low"))}.</p>"""
    if unsubscribe_url:
        body_html += f'<p><a href="{unsubscribe_url}">Відписатися від цього сповіщення</a></p>'
    message_headers = None
    if unsubscribe_url:
        message_headers = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }

    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    if _email_provider_configured():
        return _send_email(
            to_email,
            subject,
            body_text,
            body_html,
            headers=message_headers,
        )
    if sg_key:
        try:
            import urllib.request as _req, json as _json
            personalization = {"to": [{"email": to_email}]}
            if message_headers:
                personalization["headers"] = message_headers
            payload = _json.dumps({
                "personalizations": [personalization],
                "from": {"email": os.environ.get("FROM_EMAIL", "noreply@ua-dim.com")},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": body_text},
                    {"type": "text/html", "value": body_html},
                ]
            }).encode()
            req = _req.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=payload,
                headers={"Authorization": f"Bearer {sg_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with _req.urlopen(req, timeout=10) as r:
                return r.status in (200, 202)
        except Exception as e:
            app.logger.error("SendGrid alert email error: %s", e)
            return False
    if smtp_host:
        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = os.environ.get("FROM_EMAIL", "noreply@ua-dim.com")
            msg["To"] = to_email
            for header_name, header_value in (message_headers or {}).items():
                msg[header_name] = header_value
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
            msg.attach(MIMEText(body_html, "html", "utf-8"))
            smtp_port = int(os.environ.get("SMTP_PORT", 587))
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as srv:
                srv.starttls()
                srv.login(os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", ""))
                srv.sendmail(msg["From"], [to_email], msg.as_string())
            return True
        except Exception as e:
            app.logger.error("SMTP alert email error: %s", e)
            return False
    if PUBLIC_SITE_URL:
        app.logger.warning("Alert email is not configured for production (%s)", to_email)
        return False
    app.logger.info("ALERT EMAIL (dev) → %s | %s", to_email, body_text)
    return True


class _FirebasePushResult(NamedTuple):
    configured: bool
    attempted: bool
    success: bool
    invalid_tokens: tuple[str, ...] = ()


class _AlertPushOutcome(NamedTuple):
    attempted: bool
    delivered: bool


def _get_firebase_app():
    global _firebase_app, _firebase_init_failed
    if not FIREBASE_SERVICE_ACCOUNT_BASE64 or _firebase_init_failed:
        return None
    if _firebase_app is not None:
        return _firebase_app

    with _firebase_init_lock:
        if _firebase_app is not None or _firebase_init_failed:
            return _firebase_app
        try:
            import firebase_admin
            from firebase_admin import credentials

            decoded = base64.b64decode(
                FIREBASE_SERVICE_ACCOUNT_BASE64.encode("ascii"),
                validate=True,
            )
            service_account = json.loads(decoded.decode("utf-8"))
            if not isinstance(service_account, dict):
                raise ValueError("service account JSON must be an object")
            if service_account.get("type") != "service_account":
                raise ValueError("credential is not a service account")
            if service_account.get("project_id") != FIREBASE_PROJECT_ID:
                raise ValueError("credential belongs to an unexpected Firebase project")
            _firebase_app = firebase_admin.initialize_app(
                credentials.Certificate(service_account),
                {"projectId": FIREBASE_PROJECT_ID},
                name=_FIREBASE_APP_NAME,
            )
        except (
            ImportError,
            UnicodeEncodeError,
            UnicodeDecodeError,
            binascii.Error,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            _firebase_init_failed = True
            app.logger.error(
                "Firebase Admin initialization failed for %s (%s); "
                "verify that it contains base64-encoded service-account JSON for project %s",
                "UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64",
                type(exc).__name__,
                FIREBASE_PROJECT_ID,
            )
            return None
    return _firebase_app


def _firebase_notification(payload: dict) -> tuple[str, str, dict[str, str]]:
    listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
    event = str(payload.get("event") or "saved_alert_match")
    if event == "saved_alert_price_change":
        title = "Ціна оголошення змінилася"
    else:
        title = "Нове оголошення за вашим пошуком"
    body = str(listing.get("title") or payload.get("name") or "Відкрийте UA-Dim, щоб переглянути")
    city = str(listing.get("city") or "").strip()
    if city and city.lower() not in body.lower():
        body = f"{body} · {city}"
    data = {
        "event": event,
        "alert_id": str(payload.get("alert_id") or ""),
        "listing_id": str(listing.get("id") or ""),
        "url": str(listing.get("url") or ""),
    }
    return title, body, data


def _is_permanent_fcm_token_error(error, messaging, firebase_exceptions) -> bool:
    return isinstance(
        error,
        (
            messaging.UnregisteredError,
            messaging.SenderIdMismatchError,
            firebase_exceptions.InvalidArgumentError,
        ),
    )


def _send_alert_push_via_firebase(payload: dict) -> _FirebasePushResult:
    if not FIREBASE_SERVICE_ACCOUNT_BASE64:
        return _FirebasePushResult(configured=False, attempted=False, success=False)

    firebase_app = _get_firebase_app()
    if firebase_app is None:
        return _FirebasePushResult(configured=True, attempted=False, success=False)

    tokens = [
        token
        for token in payload.get("device_tokens", [])
        if isinstance(token, str) and token
    ]
    if not tokens:
        app.logger.info("Firebase push skipped because the alert has no active device tokens")
        return _FirebasePushResult(configured=True, attempted=False, success=False)

    from firebase_admin import exceptions as firebase_exceptions
    from firebase_admin import messaging

    title, body, data = _firebase_notification(payload)
    notification = messaging.Notification(title=title, body=body)
    android = messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(
            sound="default",
            click_action="FLUTTER_NOTIFICATION_CLICK",
        ),
    )
    apns = messaging.APNSConfig(
        payload=messaging.APNSPayload(aps=messaging.Aps(sound="default")),
    )
    messages = [
        messaging.Message(
            token=token,
            notification=notification,
            data=data,
            android=android,
            apns=apns,
        )
        for token in tokens
    ]
    try:
        response = messaging.send_each(messages, app=firebase_app)
    except (firebase_exceptions.FirebaseError, OSError, TimeoutError) as exc:
        app.logger.error(
            "Firebase push request failed before a response (%s); webhook fallback suppressed",
            type(exc).__name__,
        )
        return _FirebasePushResult(configured=True, attempted=True, success=False)

    invalid_tokens = tuple(
        token
        for token, send_response in zip(tokens, response.responses)
        if not send_response.success
        and _is_permanent_fcm_token_error(
            send_response.exception,
            messaging,
            firebase_exceptions,
        )
    )
    if response.failure_count:
        app.logger.warning(
            "Firebase push completed with success=%s failure=%s invalid_tokens=%s",
            response.success_count,
            response.failure_count,
            len(invalid_tokens),
        )
    return _FirebasePushResult(
        configured=True,
        attempted=True,
        success=response.success_count > 0,
        invalid_tokens=invalid_tokens,
    )


def _deactivate_push_tokens(db, tokens: tuple[str, ...]) -> None:
    if not tokens:
        return
    placeholders = ", ".join("?" for _ in tokens)
    db.execute(
        f"UPDATE push_devices SET is_active = 0 WHERE token IN ({placeholders})",
        tokens,
    )
    app.logger.info("Deactivated %s permanently invalid Firebase push token(s)", len(tokens))


def _send_alert_push_webhook(payload: dict) -> bool:
    if not ALERTS_PUSH_WEBHOOK_URL:
        return False
    try:
        import urllib.request as _req
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if ALERTS_PUSH_WEBHOOK_BEARER:
            headers["Authorization"] = f"Bearer {ALERTS_PUSH_WEBHOOK_BEARER}"
        req = _req.Request(ALERTS_PUSH_WEBHOOK_URL, data=body, headers=headers, method="POST")
        with _req.urlopen(req, timeout=10) as r:
            return r.status in (200, 201, 202, 204)
    except Exception as e:
        app.logger.error("Alerts push webhook error: %s", e)
        return False


def _deliver_alert_push_payload(payload: dict, *, db=None) -> _AlertPushOutcome:
    tokens = [
        token
        for token in payload.get("device_tokens", [])
        if isinstance(token, str) and token
    ]
    if not tokens:
        if ALERTS_PUSH_WEBHOOK_URL:
            return _AlertPushOutcome(
                attempted=True,
                delivered=_send_alert_push_webhook(payload),
            )
        return _AlertPushOutcome(attempted=False, delivered=False)
    firebase_result = _send_alert_push_via_firebase(payload)
    if db is not None:
        _deactivate_push_tokens(db, firebase_result.invalid_tokens)
    if firebase_result.attempted:
        return _AlertPushOutcome(attempted=True, delivered=firebase_result.success)
    if ALERTS_PUSH_WEBHOOK_URL:
        if firebase_result.configured:
            app.logger.warning(
                "Firebase push was unavailable before delivery; using configured webhook fallback"
            )
        return _AlertPushOutcome(
            attempted=True,
            delivered=_send_alert_push_webhook(payload),
        )
    return _AlertPushOutcome(attempted=False, delivered=False)


def send_alert_push_payload(payload: dict, *, db=None) -> bool:
    return _deliver_alert_push_payload(payload, db=db).delivered


def _listing_matches_alert_filters(listing: dict, filters: dict) -> bool:
    city = strip(filters.get("city"), 100)
    district = strip(filters.get("district"), 100)
    prop_type = strip(filters.get("type"), 50)
    listing_type = strip(filters.get("listingType"), 10).lower()
    min_price = pos_int(filters.get("minPrice"))
    max_price = pos_int(filters.get("maxPrice"))
    min_rooms = nonneg_int(filters.get("minRooms"))
    max_rooms = nonneg_int(filters.get("maxRooms"))
    min_area = nonneg_int(filters.get("minArea"))
    max_area = nonneg_int(filters.get("maxArea"))
    keyword = strip(filters.get("keywordSearch"), 120).lower()
    e_oselya = bool(filters.get("eOselya"))

    if city and listing.get("city") != city:
        return False
    if district and district.lower() not in str(listing.get("district") or "").lower():
        return False
    if prop_type and listing.get("property_type") != prop_type:
        return False
    if listing_type in {"sale", "rent"} and listing.get("listing_type") != listing_type:
        return False
    price = int(listing.get("price") or 0)
    rooms = int(listing.get("rooms") or 0)
    area = int(float(listing.get("area") or 0))
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    if min_rooms is not None and rooms < min_rooms:
        return False
    if max_rooms is not None and rooms > max_rooms:
        return False
    if min_area is not None and area < min_area:
        return False
    if max_area is not None and area > max_area:
        return False
    if keyword:
        searchable = " ".join(
            str(listing.get(field) or "")
            for field in ("title", "description", "city", "district", "property_type")
        ).lower()
        if keyword not in searchable:
            return False
    if e_oselya and not bool(listing.get("e_oselya")):
        return False
    return True


def dispatch_saved_alerts(
    db,
    listing_id: int | None = None,
    dry_run: bool = False,
    *,
    event_type: str = "new_listing",
    previous_price: int | None = None,
) -> dict:
    target_listing = None
    if listing_id is not None:
        row = db.execute(
            LISTING_SELECT + " WHERE l.id = ? AND l.status = 'published'",
            (listing_id,),
        ).fetchone()
        if row:
            target_listing = _row_to_listing(row)

    checked = 0
    matched = 0
    email_sent = 0
    push_sent = 0
    email_groups: dict[tuple[str, int, str], list[tuple[object, dict]]] = {}
    candidates: list[tuple[object, dict, list[str], str]] = []

    def delivery_recorded(
        alert_id: int, listing_value: int, channel: str, receipt_event_key: str
    ) -> bool:
        return bool(
            db.execute(
                """
                SELECT 1 FROM alert_delivery_receipts
                WHERE alert_id = ? AND listing_id = ? AND channel = ? AND event_key = ?
                """,
                (alert_id, listing_value, channel, receipt_event_key),
            ).fetchone()
        )

    def record_delivery(
        alert_id: int, listing_value: int, channel: str, receipt_event_key: str
    ) -> None:
        db.execute(
            """
            INSERT INTO alert_delivery_receipts (alert_id, listing_id, channel, event_key)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alert_id, listing_id, channel, event_key) DO NOTHING
            """,
            (alert_id, listing_value, channel, receipt_event_key),
        )

    last_alert_id = 0
    while True:
        alerts = db.execute(
            """
            SELECT la.id, la.user_id, la.email, la.email_normalized, la.name, la.filters,
                   la.last_sent_at, la.last_sent_listing_id, la.last_scanned_at,
                   la.last_scanned_listing_id, la.unsubscribe_version
            FROM listing_alerts AS la
            LEFT JOIN users AS u ON u.id = la.user_id
            WHERE la.is_active = 1 AND la.id > ?
              AND (
                la.subscription_key IS NULL
                OR la.verified_at IS NOT NULL
                OR (la.user_id IS NOT NULL AND u.email_verified = 1)
              )
            ORDER BY la.id ASC
            LIMIT ?
            """,
            (last_alert_id, ALERT_DISPATCH_BATCH_SIZE),
        ).fetchall()
        if not alerts:
            break
        for alert in alerts:
            last_alert_id = alert["id"]
            checked += 1
            try:
                filters = json.loads(alert["filters"] or "{}")
                if not isinstance(filters, dict):
                    filters = {}
            except json.JSONDecodeError:
                filters = {}
            channels_raw = filters.get("channels")
            if isinstance(channels_raw, list):
                channels = [strip(item, 20).lower() for item in channels_raw if strip(item, 20)]
            elif isinstance(channels_raw, str):
                channels = [strip(channels_raw, 20).lower()]
            else:
                channels = ["email"]
            channels = [c for c in channels if c in {"email", "push"}] or ["email"]

            candidate_listing = None
            if target_listing:
                candidate_listing = target_listing if _listing_matches_alert_filters(target_listing, filters) else None
            else:
                scan_at = alert["last_scanned_at"] or alert["last_sent_at"]
                scan_id = alert["last_scanned_listing_id"] or alert["last_sent_listing_id"]
                while True:
                    rows = db.execute(
                        LISTING_SELECT
                        + """
                            WHERE l.status = 'published'
                              AND (
                                l.created_at > COALESCE(?, '1970-01-01 00:00:00')
                                OR (
                                  l.created_at = COALESCE(?, '1970-01-01 00:00:00')
                                  AND l.id > COALESCE(?, 0)
                                )
                              )
                            ORDER BY l.created_at ASC, l.id ASC
                            LIMIT 80
                        """,
                        (scan_at, scan_at, scan_id),
                    ).fetchall()
                    if not rows:
                        break
                    for row in rows:
                        listing = _row_to_listing(row)
                        scan_at = listing.get("created_at")
                        scan_id = listing["id"]
                        if _listing_matches_alert_filters(listing, filters):
                            candidate_listing = listing
                            break
                    if candidate_listing:
                        break
                    if not dry_run:
                        db.execute(
                            """
                            UPDATE listing_alerts
                            SET last_scanned_at = ?, last_scanned_listing_id = ?
                            WHERE id = ?
                            """,
                            (scan_at, scan_id, alert["id"]),
                        )
                    if len(rows) < 80:
                        break
            if not candidate_listing:
                continue

            matched += 1
            receipt_event_key = (
                f"price_change:{previous_price}:{candidate_listing.get('price')}"
                if event_type == "price_change"
                else event_type
            )
            candidates.append((alert, candidate_listing, channels, receipt_event_key))
            if "email" in channels and not delivery_recorded(
                alert["id"], candidate_listing["id"], "email", receipt_event_key
            ):
                recipient = (alert["email_normalized"] or alert["email"]).strip().lower()
                email_groups.setdefault(
                    (recipient, candidate_listing["id"], receipt_event_key), []
                ).append((alert, candidate_listing))

            if "push" in channels and not delivery_recorded(
                alert["id"], candidate_listing["id"], "push", receipt_event_key
            ):
                device_tokens = []
                if alert["user_id"]:
                    device_tokens = [
                        row["token"]
                        for row in db.execute(
                            "SELECT token FROM push_devices WHERE user_id = ? AND is_active = 1"
                            " ORDER BY last_seen_at DESC LIMIT 20",
                            (alert["user_id"],),
                        ).fetchall()
                    ]
                push_outcome = _AlertPushOutcome(attempted=True, delivered=True) if dry_run else _deliver_alert_push_payload(
                    {
                        "event": "saved_alert_price_change" if event_type == "price_change" else "saved_alert_match",
                        "alert_id": alert["id"],
                        "user_id": alert["user_id"],
                        "email": alert["email"],
                        "name": alert["name"] or "Listing alert",
                        "device_tokens": device_tokens,
                        "listing": {
                            "id": candidate_listing["id"],
                            "title": candidate_listing.get("title"),
                            "price": candidate_listing.get("price"),
                            "previous_price": previous_price,
                            "city": candidate_listing.get("city"),
                            "district": candidate_listing.get("district"),
                            "url": (
                                f"{(PUBLIC_SITE_URL or 'http://localhost:8080').rstrip('/')}"
                                f"/listing/{candidate_listing['id']}"
                            ),
                        },
                    },
                    db=db,
                )
                if push_outcome.delivered:
                    push_sent += 1
                    if not dry_run:
                        record_delivery(
                            alert["id"], candidate_listing["id"], "push", receipt_event_key
                        )
                elif not push_outcome.attempted:
                    channels = [channel for channel in channels if channel != "push"]
                    candidates[-1] = (
                        alert,
                        candidate_listing,
                        channels,
                        receipt_event_key,
                    )

    recipient_counts: dict[str, int] = {}
    for (recipient, _listing_id, receipt_event_key), grouped in email_groups.items():
        if recipient_counts.get(recipient, 0) >= ALERT_RECIPIENT_RUN_CAP:
            continue
        alert, listing = grouped[0]
        unsubscribe_url = _alert_unsubscribe_url(
            alert["id"], int(alert["unsubscribe_version"] or 0)
        )
        email_ok = True if dry_run else send_alert_listing_email(
            alert["email"],
            alert["name"] or "Listing alert",
            listing,
            event_type=event_type,
            previous_price=previous_price,
            unsubscribe_url=unsubscribe_url,
        )
        if not email_ok:
            continue
        email_sent += 1
        recipient_counts[recipient] = recipient_counts.get(recipient, 0) + 1
        if not dry_run:
            for grouped_alert, grouped_listing in grouped:
                record_delivery(
                    grouped_alert["id"],
                    grouped_listing["id"],
                    "email",
                    receipt_event_key,
                )

    if not dry_run:
        for alert, candidate_listing, channels, receipt_event_key in candidates:
            if not all(
                delivery_recorded(
                    alert["id"], candidate_listing["id"], channel, receipt_event_key
                )
                for channel in channels
            ):
                continue
            delivered_at = (
                candidate_listing.get("created_at")
                or datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
            )
            db.execute(
                """
                UPDATE listing_alerts
                SET last_sent_at = ?, last_sent_listing_id = ?,
                    last_scanned_at = ?, last_scanned_listing_id = ?
                WHERE id = ?
                """,
                (
                    delivered_at,
                    candidate_listing["id"],
                    delivered_at,
                    candidate_listing["id"],
                    alert["id"],
                ),
            )

    if not dry_run:
        db.commit()
    return {
        "checked": checked,
        "matched": matched,
        "email_sent": email_sent,
        "push_sent": push_sent,
    }


def alerts_dispatch_authorized(db) -> tuple[bool, str]:
    request_key = strip(request.headers.get("X-Alerts-Dispatch-Key"), 500)
    if ALERTS_DISPATCH_KEY and request_key and secrets.compare_digest(request_key, ALERTS_DISPATCH_KEY):
        return True, "dispatch_key"
    user_id, is_admin = get_optional_actor(db)
    if user_id and is_admin:
        return True, "admin_token"
    return False, "unauthorized"


def log_alert_dispatch_run(
    db,
    *,
    trigger_type: str,
    dry_run: bool,
    listing_id: int | None,
    success: bool,
    started_at: datetime.datetime,
    finished_at: datetime.datetime,
    stats: dict | None = None,
    error_text: str | None = None,
):
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    stats = stats or {}
    db.execute(
        """
        INSERT INTO alert_dispatch_runs
        (trigger_type, dry_run, listing_id, checked, matched, email_sent, push_sent, success, error_text, started_at, finished_at, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strip(trigger_type, 40) or "manual",
            int(bool(dry_run)),
            listing_id,
            int(stats.get("checked") or 0),
            int(stats.get("matched") or 0),
            int(stats.get("email_sent") or 0),
            int(stats.get("push_sent") or 0),
            int(bool(success)),
            strip(error_text, 1000) if error_text else None,
            started_at.replace(microsecond=0).isoformat(sep=" "),
            finished_at.replace(microsecond=0).isoformat(sep=" "),
            duration_ms,
        ),
    )
    db.commit()


def run_dispatch_with_logging(
    db,
    *,
    trigger_type: str,
    listing_id: int | None = None,
    dry_run: bool = False,
    raise_errors: bool = False,
    event_type: str = "new_listing",
    previous_price: int | None = None,
) -> dict:
    started_at = datetime.datetime.utcnow()
    stats: dict = {"checked": 0, "matched": 0, "email_sent": 0, "push_sent": 0}
    success = False
    error_text = None
    try:
        stats = dispatch_saved_alerts(
            db,
            listing_id=listing_id,
            dry_run=dry_run,
            event_type=event_type,
            previous_price=previous_price,
        )
        success = True
        return stats
    except Exception as e:
        error_text = str(e)
        app.logger.error("Alerts dispatch failed (%s): %s", trigger_type, e)
        if raise_errors:
            raise
        return stats
    finally:
        finished_at = datetime.datetime.utcnow()
        log_alert_dispatch_run(
            db,
            trigger_type=trigger_type,
            dry_run=dry_run,
            listing_id=listing_id,
            success=success,
            started_at=started_at,
            finished_at=finished_at,
            stats=stats,
            error_text=error_text,
        )


# ─── Validation helpers ───────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-.]+$")

def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 254


def normalize_alert_email(value) -> str:
    email = strip(value, 254).lower()
    if email.count("@") != 1:
        return ""
    local, domain = email.rsplit("@", 1)
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    normalized = f"{local}@{domain}"
    return normalized if validate_email(normalized) else ""

def strip(val, max_len=255) -> str:
    return str(val or "").strip()[:max_len]

def pos_int(val) -> int | None:
    try:
        v = int(val)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None

def nonneg_int(val) -> int | None:
    try:
        v = int(val)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None

def pos_float(val) -> float | None:
    try:
        v = float(val)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def truthy_flag(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_dt(value: str | None) -> datetime.datetime | None:
    text = strip(value or "", 64)
    if not text:
        return None
    try:
        # SQLite timestamps are usually "YYYY-MM-DD HH:MM:SS"
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hours_since(value: str | None) -> int | None:
    dt = _parse_dt(value)
    if not dt:
        return None
    if dt.tzinfo is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - dt.astimezone(datetime.timezone.utc)
    else:
        now = datetime.datetime.utcnow()
        delta = now - dt
    return max(0, int(delta.total_seconds() // 3600))


def _days_since(value: str | None) -> int | None:
    dt = _parse_dt(value)
    if not dt:
        return None
    if dt.tzinfo is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - dt.astimezone(datetime.timezone.utc)
    else:
        now = datetime.datetime.utcnow()
        delta = now - dt
    return max(0, int(delta.total_seconds() // 86400))


def _row_to_listing(r, include_private: bool = False) -> dict:
    d = dict(r)
    d["region"] = d.get("region") or _infer_region_from_city(d.get("city")) or ""
    stored_images = json.loads(d.get("images") or "[]")
    stored_videos = json.loads(d.get("videos") or "[]")
    d["image_count"] = len([value for value in stored_images if isinstance(value, str) and value.strip()])
    d["video_count"] = len([value for value in stored_videos if isinstance(value, str) and value.strip()])
    d["images"] = normalize_listing_images(stored_images)
    d["videos"] = normalize_listing_videos(stored_videos)
    d["listing_status"] = d.get("listing_status") or "active"
    d["owner_verification_status"] = d.get("owner_verification_status") or verification_state_from_bool(d.get("verified_owner"))
    d["phone_verification_status"] = d.get("phone_verification_status") or verification_state_from_bool(d.get("verified_phone"))
    d["moderation_status"] = d.get("moderation_status") or moderation_state_from_status(d.get("status"))
    d["moderation_reason"] = d.get("moderation_reason") or ""
    d["listing_verification_status"] = d.get("listing_verification_status") or "unverified"
    d["verified_listing"] = d["listing_verification_status"] == "verified"
    d["seller_type"] = public_seller_type(d.get("owner_account_type"), d.get("owner_agency_slug"))
    d.pop("owner_account_type", None)
    d.pop("owner_agency_slug", None)
    if not include_private:
        # Public serialization must never leak the owner's email or internal
        # moderation notes — those are only for the owner/admin themselves.
        d.pop("owner_email", None)
        d.pop("moderation_reason", None)
        d.pop("freshness_reminder_sent_at", None)
        if not (
            d.get("verified_phone")
            and d.get("owner_phone_verified")
            and d.get("owner_phone")
        ):
            d.pop("owner_phone", None)
        d.pop("owner_phone_verified", None)
    d["has_photo_tour"] = bool(d.get("has_photo_tour"))
    d["has_video_tour"] = bool(d.get("has_video_tour"))
    d["verified_owner"] = bool(d.get("verified_owner"))
    d["verified_phone"] = bool(d.get("verified_phone"))
    d["verified_docs"] = bool(d.get("verified_docs"))
    trust_score = (
        (40 if d["verified_owner"] else 0)
        + (30 if d["verified_phone"] else 0)
        + (30 if d["verified_docs"] else 0)
    )
    d["trust_score"] = trust_score
    d["agency_verified"] = bool(d.get("agency_verified"))
    d["trust_verified_at"] = d.get("moderation_updated_at") or d.get("published_at") or d.get("created_at")
    freshness_reference = d.get("last_confirmed_at") or d.get("published_at") or d.get("created_at")
    d["freshness_hours_ago"] = _hours_since(freshness_reference)
    d["freshness_days_ago"] = _days_since(freshness_reference)
    d["needs_freshness_confirmation"] = (
        d.get("status") == "published"
        and d["listing_status"] == "active"
        and d["freshness_days_ago"] is not None
        and d["freshness_days_ago"] >= 30
    )
    d["verified_days_ago"] = _days_since(d.get("trust_verified_at"))
    verification_proofs: list[dict] = []

    def add_proof(code: str, label: str, details: str, weight: int, priority: int):
        verification_proofs.append({
            "code": code,
            "label": label,
            "details": details,
            "weight": weight,
            "priority": priority,
            "verified_at": d.get("trust_verified_at"),
        })

    if d["has_video_tour"]:
        add_proof(
            "video",
            "Перевірено по відео",
            "Є відеоогляд об'єкта для візуальної звірки стану.",
            25,
            95,
        )
    if d["has_photo_tour"]:
        add_proof(
            "tour360",
            "Є 360°/фото-тур",
            "Доступний фото-тур або панорамні матеріали оголошення.",
            20,
            85,
        )
    if d["verified_docs"]:
        add_proof(
            "documents",
            "Перевірено по документах",
            "Документи по об'єкту перевірені модерацією.",
            30,
            100,
        )
    if d["verified_owner"]:
        add_proof(
            "owner",
            "Верифіковано власника",
            "Підтверджено, що подавач має відношення до об'єкта.",
            10,
            70,
        )
    if d["verified_phone"]:
        add_proof(
            "phone",
            "Верифіковано телефон",
            "Контактний номер підтверджено.",
            10,
            65,
        )
    if d.get("moderation_updated_at"):
        add_proof(
            "inspector",
            "Перевірено інспектором",
            "Оголошення пройшло ручну перевірку модератором.",
            20,
            90,
        )

    verification_proofs.sort(key=lambda item: item["priority"], reverse=True)
    trust_evidence_score = min(100, sum(int(item["weight"]) for item in verification_proofs))
    if trust_evidence_score >= 70:
        trust_evidence_level = "strong"
    elif trust_evidence_score >= 40:
        trust_evidence_level = "medium"
    elif trust_evidence_score > 0:
        trust_evidence_level = "basic"
    else:
        trust_evidence_level = "none"
    d["verification_proofs"] = verification_proofs
    d["trust_evidence_score"] = trust_evidence_score
    d["trust_evidence_level"] = trust_evidence_level
    dup_count = int(d.get("dup_count") or 1)
    if dup_count >= 3:
        d["duplicate_risk"] = "high"
        d["duplicate_risk_score"] = 90
    elif dup_count == 2:
        d["duplicate_risk"] = "medium"
        d["duplicate_risk_score"] = 55
    else:
        d["duplicate_risk"] = "low"
        d["duplicate_risk_score"] = 10
    return d


def public_base_url() -> str:
    if PUBLIC_SITE_URL:
        return PUBLIC_SITE_URL
    return request.url_root.rstrip("/")


def public_app_base_url() -> str:
    if PUBLIC_SITE_URL:
        parsed = urlsplit(PUBLIC_SITE_URL)
        if parsed.hostname in {"localhost", "127.0.0.1"} and parsed.port in {None, 5050}:
            return f"{parsed.scheme or 'http'}://{parsed.hostname}:8080"
        return PUBLIC_SITE_URL

    parsed = urlsplit(request.url_root.rstrip("/"))
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        return f"{parsed.scheme or 'http'}://{parsed.hostname}:8080"
    return request.url_root.rstrip("/")


def public_app_url() -> str:
    base = public_app_base_url()
    if urlsplit(base).hostname in {"localhost", "127.0.0.1"}:
        return f"{base}/real-estate-demo.html"
    return f"{base}/"


def public_seller_url() -> str:
    base = public_app_base_url()
    if urlsplit(base).hostname in {"localhost", "127.0.0.1"}:
        return f"{base}/real-estate-demo.html?seller=1"
    return f"{base}/seller"


# ─── Media & Uploads Re-exports ──────────────────────────────────────────────

try:
    from media_routes import (
        _image_optimization_metadata,
        cleanup_listing_media,
        generate_presigned_upload_url,
        media_bp,
    )
except ImportError:
    try:
        from backend.media_routes import (
            _image_optimization_metadata,
            cleanup_listing_media,
            generate_presigned_upload_url,
            media_bp,
        )
    except ImportError:
        print("Warning: media_routes not found")
        media_bp = None

try:
    from system_routes import system_bp
except ImportError:
    try:
        from backend.system_routes import system_bp
    except ImportError:
        print("Warning: system_routes not found")
        system_bp = None

try:
    from content_routes import (
        _agency_metrics,
        _content_article_by_slug,
        _content_articles,
        _freshness_score,
        _response_score,
        _seo_landing_stats,
        agencies_catalog_page,
        agency_profile_page,
        content_bp,
        get_agencies,
        get_agency_profile,
        get_content_articles,
        insight_article,
        insights_hub,
    )
except ImportError:
    try:
        from backend.content_routes import (
            _agency_metrics,
            _content_article_by_slug,
            _content_articles,
            _freshness_score,
            _response_score,
            _seo_landing_stats,
            agencies_catalog_page,
            agency_profile_page,
            content_bp,
            get_agencies,
            get_agency_profile,
            get_content_articles,
            insight_article,
            insights_hub,
        )
    except ImportError:
        print("Warning: content_routes not found")
        content_bp = None

try:
    from seo_routes import (
        DEVELOPMENT_PROJECTS,
        _development_project_by_slug,
        _development_projects_for_city,
        _render_development_project_page,
        _render_seo_page,
        development_project_page,
        listing_page,
        robots_txt,
        seo_audit,
        seo_bp,
        seo_city_page,
        seo_district_page,
        seo_top_snippets,
        sitemap_xml,
    )
except ImportError:
    try:
        from backend.seo_routes import (
            DEVELOPMENT_PROJECTS,
            _development_project_by_slug,
            _development_projects_for_city,
            _render_development_project_page,
            _render_seo_page,
            development_project_page,
            listing_page,
            robots_txt,
            seo_audit,
            seo_bp,
            seo_city_page,
            seo_district_page,
            seo_top_snippets,
            sitemap_xml,
        )
    except ImportError:
        print("Warning: seo_routes not found")
        seo_bp = None


init_db()


# ─── Routes: Listings ─────────────────────────────────────────────────────────
try:
    from listing_routes import (
        LISTING_SELECT,
        _listing_recommendations,
        _listing_search_filter,
        listing_bp,
        seller_can_fast_publish,
    )
except ImportError:
    try:
        from backend.listing_routes import (
            LISTING_SELECT,
            _listing_recommendations,
            _listing_search_filter,
            listing_bp,
            seller_can_fast_publish,
        )
    except ImportError:
        print("Warning: listing_routes not found")
        listing_bp = None




# ─── Re-exports from modular blueprints ──────────────────────────────────────

try:
    from payment_routes import (
        LIQPAY_FAILURE_STATUSES,
        LIQPAY_MODES,
        _is_external_https_base_url,
        _liqpay_amount_matches,
        _liqpay_config,
        _liqpay_encode,
        _liqpay_sign,
        payment_bp,
        resolve_plan_id,
    )
except ImportError:
    try:
        from backend.payment_routes import (
            LIQPAY_FAILURE_STATUSES,
            LIQPAY_MODES,
            _is_external_https_base_url,
            _liqpay_amount_matches,
            _liqpay_config,
            _liqpay_encode,
            _liqpay_sign,
            payment_bp,
            resolve_plan_id,
        )
    except ImportError:
        print("Warning: payment_routes not found")
        payment_bp = None

# ─── Register Blueprints ──────────────────────────────────────────────────

# Import and register listing blueprint
if listing_bp is not None:
    app.register_blueprint(listing_bp)

# Import and register media blueprint
if media_bp is not None:
    app.register_blueprint(media_bp)

# Import and register system blueprint
if system_bp is not None:
    app.register_blueprint(system_bp)

# Import and register content blueprint
if content_bp is not None:
    app.register_blueprint(content_bp)

# Import and register seo blueprint
if seo_bp is not None:
    app.register_blueprint(seo_bp)

# Import and register auth blueprint
try:
    from auth_routes import auth_bp
    app.register_blueprint(auth_bp)
except ImportError:
    try:
        from backend.auth_routes import auth_bp
        app.register_blueprint(auth_bp)
    except ImportError:
        print("Warning: auth_routes not found")

# Import and register payment blueprint
if payment_bp is not None:
    app.register_blueprint(payment_bp)

# Import and register admin blueprint
try:
    from admin_routes import admin_bp
    app.register_blueprint(admin_bp)
except ImportError:
    try:
        from backend.admin_routes import admin_bp
        app.register_blueprint(admin_bp)
    except ImportError:
        print("Warning: admin_routes not found")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"UA Homes API v2 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
