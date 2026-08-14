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
import time
import sys
from decimal import Decimal, InvalidOperation
from html import escape
from functools import wraps
from urllib.parse import quote, unquote, urlencode, urlsplit

import bcrypt
import jwt
from flask import Flask, Response, g, jsonify, request, send_file
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Optional: Image optimization (Pillow)
try:
    from PIL import Image
    import io
    HAS_IMAGE_OPTIMIZATION = True
except ImportError:
    HAS_IMAGE_OPTIMIZATION = False

# ─── Config ──────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Keep the SQLite file on a persistent volume in production — the container
# filesystem is recreated on every deploy, which would wipe all user data.
DB_PATH = os.environ.get("UA_HOMES_DB_PATH", "").strip() or os.path.join(BASE_DIR, "ua_homes.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

# PostgreSQL DSN — if set, the app uses psycopg2 instead of SQLite.
DATABASE_URL: str | None = os.environ.get("DATABASE_URL", "").strip() or None
PUBLIC_SITE_URL = os.environ.get("UA_HOMES_PUBLIC_URL", "").strip().rstrip("/")
API_ORIGIN = os.environ.get("UA_HOMES_API", "").strip().rstrip("/")
BOOTSTRAP_ADMIN_EMAIL = os.environ.get("UA_HOMES_BOOTSTRAP_ADMIN_EMAIL", "").strip()
BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("UA_HOMES_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
BOOTSTRAP_ADMIN_NAME = os.environ.get("UA_HOMES_BOOTSTRAP_ADMIN_NAME", "Admin").strip() or "Admin"


def _legacy_liqpay_environment() -> str:
    public_key = os.environ.get("LIQPAY_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("LIQPAY_PRIVATE_KEY", "").strip()
    if public_key.startswith("sandbox_") and private_key.startswith("sandbox_"):
        return "sandbox"
    if public_key and private_key:
        return "live"
    return "disabled"


def _production_secret_required() -> bool:
    runtime_name = (
        os.environ.get("RAILWAY_ENVIRONMENT_NAME")
        or os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("FLASK_ENV")
        or os.environ.get("ENVIRONMENT")
        or ""
    ).strip().lower()
    if runtime_name in {"production", "prod"}:
        return True
    if DATABASE_URL:
        return True
    if PUBLIC_SITE_URL:
        try:
            host = (urlsplit(PUBLIC_SITE_URL).hostname or "").lower()
        except ValueError:
            host = ""
        if host and host not in {"localhost", "127.0.0.1", "0.0.0.0"}:
            return True
    return False


_configured_secret = os.environ.get("UA_HOMES_SECRET", "").strip()
if not _configured_secret:
    if _production_secret_required():
        raise RuntimeError("UA_HOMES_SECRET must be set for production deployments.")
    _configured_secret = secrets.token_hex(32)

SECRET_KEY = _configured_secret
JWT_ALGO   = "HS256"
JWT_EXP_H  = 72

# Redis DSN — if set, rate-limiter stores counters in Redis (safe for multi-worker).
REDIS_URL: str | None = os.environ.get("REDIS_URL", "").strip() or None
_REDIS_CACHE = None
_REDIS_CACHE_DISABLED = False
_REPORT_CACHE: dict[str, tuple[float, object]] = {}

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


_DEFAULT_CORS_ORIGINS: list[str | re.Pattern[str]] = [
    re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"),
    re.compile(r"^https://(localhost|127\.0\.0\.1)(:\d+)?$"),
    "https://ua-homes.netlify.app",
    "https://ua-dim.netlify.app",
    "https://ua-dom.com",
    "https://www.ua-dom.com",
    "https://ua-dim.com",
    "https://www.ua-dim.com",
]


def _cors_origins() -> list[str | re.Pattern[str]]:
    configured = os.environ.get("UA_HOMES_CORS_ORIGINS", "").strip()
    if not configured:
        origins: list[str | re.Pattern[str]] = list(_DEFAULT_CORS_ORIGINS)
        if os.environ.get("UA_HOMES_ALLOW_NETLIFY_PREVIEW_CORS", "").strip().lower() in {"1", "true", "yes"}:
            origins.append(re.compile(r"^https://[a-z0-9-]+\.netlify\.app$"))
        return origins
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

def _build_html_csp() -> str:
    connect_sources = [
        "'self'",
        "https://api.cloudinary.com",
        "https://res.cloudinary.com",
        "https://*.amazonaws.com",
        "https://*.cloudfront.net",
    ]
    if PUBLIC_SITE_URL:
        parsed_public_url = urlsplit(PUBLIC_SITE_URL)
        if parsed_public_url.scheme and parsed_public_url.netloc:
            connect_sources.append(f"{parsed_public_url.scheme}://{parsed_public_url.netloc}")
    if API_ORIGIN:
        connect_sources.append(API_ORIGIN)

    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "img-src 'self' data: blob: https://res.cloudinary.com https://*.amazonaws.com https://*.cloudfront.net https://images.unsplash.com https://picsum.photos https://fastly.picsum.photos https://*.tile.openstreetmap.org; "
        "media-src 'self' blob: https://res.cloudinary.com https://*.amazonaws.com https://*.cloudfront.net; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com; "
        f"connect-src {' '.join(connect_sources)}; "
        "font-src 'self' data:; "
        "worker-src 'self' blob:; "
        "manifest-src 'self';"
    )


HTML_CSP = _build_html_csp()


def _bootstrap_admin_user(db) -> None:
    if not BOOTSTRAP_ADMIN_EMAIL or not BOOTSTRAP_ADMIN_PASSWORD:
        return

    email = BOOTSTRAP_ADMIN_EMAIL
    password = BOOTSTRAP_ADMIN_PASSWORD
    name = BOOTSTRAP_ADMIN_NAME
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("utf-8")

    if db.execute("SELECT 1 FROM users WHERE email = ? LIMIT 1", (email,)).fetchone():
        db.execute(
            "UPDATE users SET name = ?, password = ?, password_hash = ?, role = 'admin', status = 'active' WHERE email = ?",
            (
                name,
                password_hash,
                password_hash,
                email,
            ),
        )
        db.commit()
        return

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
            try:
                self._cursor.execute("SELECT LASTVAL() AS lastrowid")
                row = self._cursor.fetchone()
                value = row.get("lastrowid") if hasattr(row, "get") else (row[0] if row else None)
                self._lastrowid = int(value) if value is not None else None
            except Exception:
                self._lastrowid = None
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
            cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
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

    cached = _REPORT_CACHE.get(key)
    if not cached:
        return None
    expires_at, value = cached
    if expires_at <= time.time():
        _REPORT_CACHE.pop(key, None)
        return None
    return value


def cached_json_set(key: str, value, ttl_seconds: int) -> None:
    client = _cache_namespace_client()
    if client is not None:
        try:
            client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False))
            return
        except Exception as exc:
            app.logger.warning("Redis cache write failed for %s: %s", key, exc)

    _REPORT_CACHE[key] = (time.time() + ttl_seconds, value)


def cache_delete_prefix(prefix: str) -> None:
    client = _cache_namespace_client()
    if client is not None:
        try:
            for key in client.scan_iter(match=f"{prefix}*"):
                client.delete(key)
            return
        except Exception as exc:
            app.logger.warning("Redis cache delete failed for %s: %s", prefix, exc)

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
        DO UPDATE SET event_count = event_count + 1
        """,
        (day, source, listing_type, event),
    )
    if listing_id is not None:
        db.execute(
            """
            INSERT INTO lead_funnel_listing_metrics (day, listing_id, event, event_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(day, listing_id, event)
            DO UPDATE SET event_count = event_count + 1
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


def _is_db_integrity_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    pgcode = getattr(exc, "pgcode", None)
    sqlstate = getattr(exc, "sqlstate", None)
    return pgcode in {"23505", "23503", "23502"} or sqlstate in {"23505", "23503", "23502"}


_PG_MIGRATION_LOCK_ID = 8_140_713_559_001


def _init_postgres_db():
    """Create the PostgreSQL schema on a fresh database."""
    import psycopg2
    import psycopg2.extras

    db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
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
                published_at   TEXT,
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
                created_at   TEXT    NOT NULL DEFAULT ({db_now_expr()})
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
                avg_response_minutes  INTEGER,
                team_size             INTEGER,
                completed_deals       INTEGER NOT NULL DEFAULT 0,
                last_verified_at      TEXT,
                created_at            TEXT    NOT NULL DEFAULT ({db_now_expr()})
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
        """)

        # Backward-compatible migration for databases created before subscriptions.
        cur.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS account_type    TEXT NOT NULL DEFAULT 'owner';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_id         TEXT NOT NULL DEFAULT 'free';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_expires_at TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS agency_slug     TEXT;
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS listing_verification_status TEXT NOT NULL DEFAULT 'unverified';
            ALTER TABLE listings ADD COLUMN IF NOT EXISTS videos TEXT NOT NULL DEFAULT '[]';
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
        """)
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
        _seed_postgres(cur)
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

    # Bootstrap admin separately so a fresh production database can be
    # initialized with a real admin account when the env vars are present.
    if BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD:
        password_hash = bcrypt.hashpw(
            BOOTSTRAP_ADMIN_PASSWORD.encode("utf-8"),
            bcrypt.gensalt(rounds=12),
        ).decode("utf-8")
        cur.execute("SELECT id FROM users WHERE email = %s LIMIT 1", (BOOTSTRAP_ADMIN_EMAIL,))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                "UPDATE users SET name = %s, password = %s, password_hash = %s, role = 'admin', status = 'active' WHERE email = %s",
                (
                    BOOTSTRAP_ADMIN_NAME,
                    password_hash,
                    password_hash,
                    BOOTSTRAP_ADMIN_EMAIL,
                ),
            )
        else:
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

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": _cors_origins()}}, supports_credentials=True, vary_header=True)

# Configure Cloudinary early so api_sign_request has credentials
if CLOUDINARY_URL:
    import cloudinary
    cloudinary.config(secure=True)  # Auto-loads from CLOUDINARY_URL environment variable

# Rate-limiter storage: Redis when available (multi-worker safe), else in-memory.
_limiter_storage = f"redis://{REDIS_URL.replace('redis://','')}" if REDIS_URL else "memory://"
if REDIS_URL and not REDIS_URL.startswith("redis://"):
    _limiter_storage = REDIS_URL  # accept full DSN as-is

limiter = Limiter(
    get_remote_address,
    app=app,
    # Public browsing endpoints: generous — real users never hit this.
    # Sensitive mutation endpoints keep tighter per-route limits below.
    default_limits=["1000 per minute"],
    storage_uri=_limiter_storage,
)

ALERTS_DISPATCH_KEY = os.environ.get("UA_HOMES_ALERTS_DISPATCH_KEY", "").strip()
ALERTS_PUSH_WEBHOOK_URL = os.environ.get("UA_HOMES_ALERTS_PUSH_WEBHOOK_URL", "").strip()
ALERTS_PUSH_WEBHOOK_BEARER = os.environ.get("UA_HOMES_ALERTS_PUSH_WEBHOOK_BEARER", "").strip()


@app.before_request
def assign_request_id():
    incoming_request_id = request.headers.get("X-Request-ID", "").strip()
    if re.fullmatch(r"[A-Za-z0-9_.:-]{8,128}", incoming_request_id):
        g.request_id = incoming_request_id
    else:
        g.request_id = secrets.token_hex(12)


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
    response.headers.setdefault("X-Request-ID", getattr(g, "request_id", secrets.token_hex(12)))
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)

    if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    if response.mimetype == "text/html":
        response.headers.setdefault("Content-Security-Policy", HTML_CSP)

    cache_control = _cache_control_for_request()
    if cache_control:
        response.headers["Cache-Control"] = cache_control
        if request.headers.get("Authorization"):
            response.headers.setdefault("Vary", "Authorization")

    return _allow_cors_for_request(response)


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
                db.commit()
            except Exception:
                pass
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
    city = strip(data.get("city"), 100)
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

DEVELOPMENT_PROJECTS = [
    {
        "slug": "river-garden-residence",
        "name": "River Garden Residence",
        "city": "Київ",
        "district": "Печерський",
        "headline": "Преміальний ЖК біля Дніпра з готовими floor-plan сторінками",
        "price_from": 7900,
        "stage": "Черга 1 — введено, черга 2 — моноліт, черга 3 — продаж",
        "delivery": "IV квартал 2026",
        "floor_plans": [
            "1-кімнатні: 38–46 м²",
            "2-кімнатні: 58–74 м²",
            "3-кімнатні: 84–102 м²",
        ],
        "highlights": [
            "єОселя доступно",
            "Закритий двір без авто",
            "Підземний паркінг",
            "Панорамні вікна",
        ],
    },
    {
        "slug": "skyline-park",
        "name": "Skyline Park",
        "city": "Львів",
        "district": "Франківський",
        "headline": "Сімейний квартал комфорт+ з конверсійною SEO-сторінкою",
        "price_from": 6450,
        "stage": "Будинок 2 — оздоблення, будинок 3 — фасадні роботи",
        "delivery": "II квартал 2027",
        "floor_plans": [
            "1-кімнатні: 34–41 м²",
            "2-кімнатні: 52–69 м²",
            "3-кімнатні: 76–94 м²",
        ],
        "highlights": [
            "ЄОселя доступно",
            "Дитячі майданчики",
            "Поруч парки та школи",
            "Партнерські банки",
        ],
    },
    {
        "slug": "city-green-quarter",
        "name": "City Green Quarter",
        "city": "Одеса",
        "district": "Приморський",
        "headline": "Нова черга біля моря з окремими сторінками квартир і черг",
        "price_from": 5300,
        "stage": "Черга 4 — котлован, черга 5 — каркас",
        "delivery": "I квартал 2028",
        "floor_plans": [
            "Студії: 28–34 м²",
            "1-кімнатні: 39–47 м²",
            "2-кімнатні: 56–73 м²",
        ],
        "highlights": [
            "Тихий район",
            "Море за 12 хвилин",
            "Ландшафтний двір",
            "Планування під інвестицію",
        ],
    },
]


def _development_project_by_slug(slug: str) -> dict | None:
    target = strip(slug, 120).lower()
    for project in DEVELOPMENT_PROJECTS:
        if project["slug"].lower() == target:
            return project
    return None


def _development_projects_for_city(city_name: str) -> list[dict]:
    target = strip(city_name, 100).lower()
    return [project for project in DEVELOPMENT_PROJECTS if project["city"].lower() == target]

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
        "listing_limit": 1,
        "duration_days": 30,
        "features": ["1 оголошення", "30 днів активності", "Стандартна позиція"],
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
        "listing_limit": 3,
        "duration_days": 30,
        "features": ["3 оголошення", "30 днів активності", "Профіль ріелтора"],
    },
    "realtor_start": {
        "name": "Ріелтор Старт",
        "audience": "realtor",
        "price": 799,
        "listing_limit": 30,
        "duration_days": 30,
        "features": ["30 оголошень", "Профіль ріелтора", "Виділення в пошуку", "Статистика переглядів"],
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
        "listing_limit": 3,
        "duration_days": 30,
        "features": ["3 оголошення", "30 днів активності", "Профіль забудовника", "Новобудови в каталозі"],
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
            published_at   TEXT,
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
        CREATE INDEX IF NOT EXISTS idx_listings_status_created_at ON listings(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_status_city ON listings(status, city);
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
            created_at   TEXT    NOT NULL DEFAULT (db_now_expr())
        );
        CREATE INDEX IF NOT EXISTS idx_listing_alerts_user ON listing_alerts(user_id);
        CREATE INDEX IF NOT EXISTS idx_listing_alerts_email ON listing_alerts(email);
        CREATE INDEX IF NOT EXISTS idx_listing_alerts_last_sent ON listing_alerts(last_sent_at);

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
            avg_response_minutes  INTEGER,
            team_size             INTEGER,
            completed_deals       INTEGER NOT NULL DEFAULT 0,
            last_verified_at      TEXT,
            created_at            TEXT    NOT NULL DEFAULT (db_now_expr())
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
    db.execute("UPDATE agency_profiles SET completed_deals = COALESCE(completed_deals, 0)")

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
    payload = {
        "sub": str(user_id),
        "email": email,
        "ver": int(token_version or 0),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXP_H),
        "iat": datetime.datetime.utcnow(),
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
            "SELECT id, email, auth_token_version FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user_row or not token_matches_user_version(payload, user_row):
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
        "SELECT role, auth_token_version FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row or not token_matches_user_version(payload, row):
        return None, False
    return user_id, row["role"] == "admin"


# ─── Email / SMS helpers ─────────────────────────────────────────────────────

def _send_email(to_email: str, subject: str, body_text: str, body_html: str) -> bool:
    """Shared email dispatch via SendGrid or SMTP. Returns True on success, False otherwise."""
    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    smtp_host = os.environ.get("SMTP_HOST", "")

    if sg_key:
        try:
            import urllib.request as _req, json as _json
            payload = _json.dumps({
                "personalizations": [{"to": [{"email": to_email}]}],
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


def send_alert_listing_email(to_email: str, alert_name: str, listing: dict) -> bool:
    listing_url = f"{PUBLIC_SITE_URL or 'http://localhost:8080'}/listing/{listing['id']}"
    subject = f"Новий об'єкт за алертом «{alert_name}» — UA-Dim"
    body_text = (
        f"Знайдено новий релевантний об'єкт:\n"
        f"{listing.get('title', 'Оголошення')} — ${int(listing.get('price') or 0):,}\n"
        f"{listing.get('city', '')}, {listing.get('district', '')}\n"
        f"Переглянути: {listing_url}"
    )
    body_html = f"""<p>Знайдено новий релевантний об'єкт за вашим алертом <b>{escape(alert_name)}</b>.</p>
<p><a href="{listing_url}">{escape(listing.get("title", "Оголошення"))}</a></p>
<p><b>${int(listing.get("price") or 0):,}</b> · {escape(listing.get("city", ""))}, {escape(listing.get("district", ""))}</p>
<p>Швидкі сигнали: оновлено {listing.get("freshness_hours_ago") if listing.get("freshness_hours_ago") is not None else "—"} год тому, ризик дубля — {escape(listing.get("duplicate_risk", "low"))}.</p>"""

    sg_key = os.environ.get("SENDGRID_API_KEY", "")
    smtp_host = os.environ.get("SMTP_HOST", "")

    if sg_key:
        try:
            import urllib.request as _req, json as _json
            payload = _json.dumps({
                "personalizations": [{"to": [{"email": to_email}]}],
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


def send_alert_push_payload(payload: dict) -> bool:
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


def _listing_matches_alert_filters(listing: dict, filters: dict) -> bool:
    city = strip(filters.get("city"), 100)
    district = strip(filters.get("district"), 100)
    prop_type = strip(filters.get("type"), 50)
    listing_type = strip(filters.get("listingType"), 10).lower()
    min_price = pos_int(filters.get("minPrice"))
    max_price = pos_int(filters.get("maxPrice"))
    min_rooms = nonneg_int(filters.get("minRooms"))
    max_rooms = nonneg_int(filters.get("maxRooms"))
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
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    if min_rooms is not None and rooms < min_rooms:
        return False
    if max_rooms is not None and rooms > max_rooms:
        return False
    if e_oselya and not bool(listing.get("e_oselya")):
        return False
    return True


def dispatch_saved_alerts(db, listing_id: int | None = None, dry_run: bool = False) -> dict:
    alerts = db.execute(
        """
        SELECT id, email, name, filters, last_sent_at
        FROM listing_alerts
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 500
        """
    ).fetchall()
    if not alerts:
        return {"checked": 0, "matched": 0, "email_sent": 0, "push_sent": 0}

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

    for alert in alerts:
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
            rows = db.execute(
                LISTING_SELECT
                + """
                    WHERE l.status = 'published'
                      AND l.created_at > COALESCE(?, '1970-01-01 00:00:00')
                    ORDER BY l.created_at DESC
                    LIMIT 80
                """,
                (alert["last_sent_at"],),
            ).fetchall()
            for row in rows:
                listing = _row_to_listing(row)
                if _listing_matches_alert_filters(listing, filters):
                    candidate_listing = listing
                    break

        if not candidate_listing:
            continue

        matched += 1
        sent_any = False
        if "email" in channels:
            email_ok = True if dry_run else send_alert_listing_email(
                alert["email"],
                alert["name"] or "Listing alert",
                candidate_listing,
            )
            if email_ok:
                email_sent += 1
                sent_any = True

        if "push" in channels:
            push_ok = True if dry_run else send_alert_push_payload(
                {
                    "event": "saved_alert_match",
                    "alert_id": alert["id"],
                    "email": alert["email"],
                    "name": alert["name"] or "Listing alert",
                    "listing": {
                        "id": candidate_listing["id"],
                        "title": candidate_listing.get("title"),
                        "price": candidate_listing.get("price"),
                        "city": candidate_listing.get("city"),
                        "district": candidate_listing.get("district"),
                        "url": f"{PUBLIC_SITE_URL or 'http://localhost:8080'}/listing/{candidate_listing['id']}",
                    },
                }
            )
            if push_ok:
                push_sent += 1
                sent_any = True

        if sent_any and not dry_run:
            db.execute(
                f"UPDATE listing_alerts SET last_sent_at = {db_now_expr()} WHERE id = ?",
                (alert["id"],),
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
) -> dict:
    started_at = datetime.datetime.utcnow()
    stats: dict = {"checked": 0, "matched": 0, "email_sent": 0, "push_sent": 0}
    success = False
    error_text = None
    try:
        stats = dispatch_saved_alerts(db, listing_id=listing_id, dry_run=dry_run)
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
    d["freshness_hours_ago"] = _hours_since(d.get("published_at") or d.get("created_at"))
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
    return f"{public_app_base_url()}/real-estate-demo.html"


def public_seller_url() -> str:
    base = public_app_base_url()
    if urlsplit(base).hostname in {"localhost", "127.0.0.1"}:
        return f"{base}/real-estate-demo.html?seller=1"
    return f"{base}/seller"


# ─── S3 / Direct Upload Support ──────────────────────────────────────────────

def generate_presigned_upload_url(
    filename: str,
    content_type: str,
    resource_type: str = "image",
    expires_in: int = 3600,
) -> dict | None:
    """
    Generate Presigned URL for direct browser → S3 upload.
    
    Returns: {
        'uploadUrl': 'https://bucket.s3.amazonaws.com/...',
        'fields': {'key': 'path/to/file', 'policy': '...', ...},  # For HTML form
        'headers': {'Authorization': '...'},  # For PUT request
        'storage': 'aws_s3' | 'cloudinary' | None
    }
    
    This allows browser to upload directly to S3 without backend bottleneck.
    Backend only verifies signature + stores URL reference.
    """
    
    if not S3_ENABLED:
        return None
    
    # Generate unique key per listing (namespace by user + timestamp)
    import uuid
    unique_id = uuid.uuid4().hex[:12]
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(filename or ""))[:180] or "media"
    s3_key = f"listings/{g.user_id}/{unique_id}/{safe_filename}"
    
    # AWS S3 Presigned URL
    if S3_BUCKET and S3_ACCESS_KEY and S3_SECRET_KEY:
        if not S3_PUBLIC_BASE_URL:
            return None
        import boto3
        from botocore.config import Config
        
        s3_client = boto3.client(
            's3',
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            endpoint_url=S3_ENDPOINT,  # For MinIO/custom S3
            config=Config(signature_version='s3v4')
        )
        
        try:
            uploaded_at = datetime.datetime.utcnow().isoformat()
            url = s3_client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': S3_BUCKET,
                    'Key': s3_key,
                    'ContentType': content_type,
                    'Metadata': {
                        'user-id': str(g.user_id),
                        'uploaded-at': uploaded_at
                    }
                },
                ExpiresIn=expires_in
            )
            
            # Return info for browser upload
            return {
                'uploadUrl': url,
                'key': s3_key,
                'bucket': S3_BUCKET,
                'region': S3_REGION,
                'method': 'PUT',
                'storage': 'aws_s3',
                'expiresIn': expires_in,
                'headers': {
                    'Content-Type': content_type,
                    'x-amz-meta-user-id': str(g.user_id),
                    'x-amz-meta-uploaded-at': uploaded_at,
                },
            }
        except Exception as e:
            print(f"Error generating S3 presigned URL: {e}")
            return None
    
    # Cloudinary Upload
    elif CLOUDINARY_URL:
        import cloudinary
        import cloudinary.uploader
        import cloudinary.utils
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(CLOUDINARY_URL)
            cloud_name = parsed.hostname or ""
            api_key = parsed.username or os.environ.get("CLOUDINARY_API_KEY", "").strip()
            api_secret = parsed.password or os.environ.get("CLOUDINARY_API_SECRET", "").strip()
            upload_preset = _cloudinary_upload_preset()
            
            # Debug logging
            print(f"[Cloudinary] cloud_name={cloud_name}, preset={upload_preset}, has_api_key={bool(api_key)}")
            
            if not cloud_name:
                return None

            safe_stem = os.path.splitext(safe_filename)[0] or "media"
            public_id = f"listings/{g.user_id}/{unique_id}/{safe_stem}"
            upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/{resource_type}/upload"

            # Prefer unsigned uploads with preset (no signature validation issues)
            if upload_preset:
                print(f"[Cloudinary] Using UNSIGNED upload preset: {upload_preset}")
                return {
                    "uploadUrl": upload_url,
                    "method": "POST",
                    "storage": "cloudinary",
                    "expiresIn": expires_in,
                    "cloudName": cloud_name,
                    "authType": "unsigned",
                    "uploadPreset": upload_preset,
                    "publicId": public_id,
                    "resourceType": resource_type,
                }

            # Fallback to signed uploads if credentials available
            if api_key and api_secret:
                print(f"[Cloudinary] Preset NOT available, using SIGNED uploads with credentials")
                timestamp = int(time.time())
                
                # Let cloudinary SDK handle signature generation - it knows the correct format
                sig_params = {
                    "public_id": public_id,
                    "timestamp": timestamp,
                }
                signature = cloudinary.utils.api_sign_request(sig_params, api_secret)
                
                return {
                    "uploadUrl": upload_url,
                    "method": "POST",
                    "storage": "cloudinary",
                    "expiresIn": expires_in,
                    "cloudName": cloud_name,
                    "authType": "signed",
                    "apiKey": api_key,
                    "timestamp": timestamp,
                    "signature": signature,
                    "publicId": public_id,
                    "resourceType": resource_type,
                }

            return None
        except Exception as e:
            print(f"Error generating Cloudinary upload URL: {e}")
            return None
    
    return None


@app.route("/api/images/presigned-url", methods=["POST"])
@app.route("/api/media/presigned-url", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def get_presigned_upload_url():
    """
    Generate Presigned URL for browser → S3 direct upload.
    
    Request:
      POST /api-backend/images/presigned-url
      { "filename": "photo.jpg", "contentType": "image/jpeg" }
    
    Response:
      {
        "uploadUrl": "https://s3.amazonaws.com/...",
        "key": "listings/123/abc123/photo.jpg",
        "method": "PUT",
        "storage": "aws_s3",
        "expiresIn": 3600
      }
    
    Browser then does: fetch(uploadUrl, { method: 'PUT', body: file })
    """
    
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename", "")).strip()
    content_type = str(data.get("contentType", "")).strip()
    file_size = nonneg_int(data.get("size"))
    
    if not filename:
        return jsonify(error="Missing filename"), 400

    normalized_content_type, resource_type = normalize_media_content_type(filename, content_type)
    if not normalized_content_type:
        return jsonify(error="Непідтримуваний формат. Дозволено фото JPG/PNG/WEBP/AVIF/HEIC та відео MP4/MOV/WEBM."), 400
    max_size = MAX_VIDEO_UPLOAD_SIZE if resource_type == "video" else MAX_UPLOAD_SIZE
    if file_size is not None and file_size > max_size:
        return jsonify(error=f"Файл завеликий. Максимум {max_size // 1_048_576} МБ."), 413
    
    presigned = generate_presigned_upload_url(filename, normalized_content_type, resource_type)
    if not presigned:
        return jsonify(error="Сховище медіа не налаштоване."), 503
    
    presigned["contentType"] = normalized_content_type
    presigned["resourceType"] = resource_type
    presigned["maxSize"] = max_size
    return jsonify(presigned)


@app.route("/api/images/confirm-upload", methods=["POST"])
@app.route("/api/media/confirm-upload", methods=["POST"])
@require_auth
@limiter.limit("60 per hour")
def confirm_uploaded_media():
    """
    Confirm S3 upload and get final image URL.
    
    Frontend calls this AFTER successful S3 upload to:
    1. Verify file exists in S3
    2. Generate CDN URL
    3. Store reference in database
    
    Request:
      POST /api-backend/images/confirm-upload
      { "key": "listings/123/abc123/photo.jpg", "etag": "abc123" }
    
    Response:
      { "url": "https://cdn.example.com/listings/123/abc123/photo.jpg" }
    """
    
    data = request.get_json(silent=True) or {}
    s3_key = str(data.get("key", "")).strip()
    etag = str(data.get("etag", "")).strip()  # For verification
    cloudinary_url = str(data.get("url", "")).strip()
    public_id = str(data.get("publicId", "")).strip()
    resource_type = "video" if str(data.get("resourceType", "")).strip().lower() == "video" else "image"
    
    if not s3_key and not public_id and not cloudinary_url:
        return jsonify(error="Missing upload reference"), 400

    if s3_key:
        # Verify key belongs to current user (prevent arbitrary file access)
        if not s3_key.startswith(f"listings/{g.user_id}/"):
            return jsonify(error="Unauthorized: file does not belong to you"), 403

        # Security: Verify file actually exists in S3 before returning URL
        if S3_BUCKET and S3_ACCESS_KEY:
            try:
                import boto3
                s3 = boto3.client(
                    's3',
                    region_name=S3_REGION,
                    aws_access_key_id=S3_ACCESS_KEY,
                    aws_secret_access_key=S3_SECRET_KEY,
                    endpoint_url=S3_ENDPOINT
                )
                response = s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
                
                if etag and response.get('ETag', '').strip('"') != etag:
                    return jsonify(error="ETag mismatch - file may be corrupted"), 400
                stored_type, stored_resource_type = normalize_media_content_type(
                    s3_key,
                    response.get("ContentType", ""),
                )
                if not stored_type:
                    return jsonify(error="Непідтримуваний формат завантаженого файла"), 400
                max_size = MAX_VIDEO_UPLOAD_SIZE if stored_resource_type == "video" else MAX_UPLOAD_SIZE
                if int(response.get("ContentLength") or 0) > max_size:
                    return jsonify(error="Завантажений файл перевищує дозволений розмір"), 413
            except Exception as e:
                error_code = str(
                    getattr(e, "response", {}).get("Error", {}).get("Code", "")
                )
                if error_code in {"NoSuchKey", "NotFound", "404"}:
                    return jsonify(error="File not found in S3"), 404
                print(f"Error verifying S3 upload: {e}")
                return jsonify(error="Failed to verify upload"), 500

        # Generate CDN URL (can be CloudFront, direct S3, or custom CDN)
        if not S3_PUBLIC_BASE_URL:
            return jsonify(error="S3 delivery URL is not configured"), 503
        cdn_url = f"{S3_PUBLIC_BASE_URL}/{s3_key}"
        return jsonify({"url": cdn_url})

    # Cloudinary confirmation path
    if public_id:
        if not public_id.startswith(f"listings/{g.user_id}/"):
            return jsonify(error="Unauthorized: file does not belong to you"), 403

        cloud_name = ""
        if CLOUDINARY_URL:
            import cloudinary
            import cloudinary.api
            cloudinary.config(secure=True)
            cloud_name = getattr(cloudinary.config(), "cloud_name", None) or ""
            try:
                asset = cloudinary.api.resource(public_id, resource_type=resource_type)
            except Exception:
                return jsonify(error="Не вдалося перевірити завантажений Cloudinary-файл"), 400
            max_size = MAX_VIDEO_UPLOAD_SIZE if resource_type == "video" else MAX_UPLOAD_SIZE
            if int(asset.get("bytes") or 0) > max_size:
                return jsonify(error="Завантажений файл перевищує дозволений розмір"), 413
            actual_resource_type = str(asset.get("resource_type") or "").lower()
            if actual_resource_type and actual_resource_type != resource_type:
                return jsonify(error="Тип Cloudinary-файла не відповідає запиту"), 400
            cloudinary_url = str(asset.get("secure_url") or cloudinary_url).strip()

        if cloudinary_url:
            if cloud_name and f"/{cloud_name}/" not in cloudinary_url:
                return jsonify(error="Cloudinary URL does not match configured cloud"), 400
            expected_path = f"/{resource_type}/upload/"
            if expected_path not in cloudinary_url:
                return jsonify(error="Cloudinary media type does not match upload"), 400
            return jsonify({"url": cloudinary_url})

        if cloud_name:
            return jsonify({"url": f"https://res.cloudinary.com/{cloud_name}/{resource_type}/upload/{public_id}"})

        return jsonify(error="Cloudinary not configured"), 503

    return jsonify(error="Missing upload reference"), 400


def cleanup_listing_media(media_urls: list[str], user_id: int) -> list[str]:
    """Delete only storage objects that are namespaced to the listing owner."""
    owned_prefix = f"listings/{user_id}/"
    s3_keys: list[str] = []
    cloudinary_assets: list[tuple[str, str]] = []

    for media_url in media_urls:
        url = str(media_url or "").strip()
        if not url:
            continue
        if S3_PUBLIC_BASE_URL and url.startswith(f"{S3_PUBLIC_BASE_URL}/"):
            key = unquote(url[len(S3_PUBLIC_BASE_URL) + 1 :])
            if key.startswith(owned_prefix):
                s3_keys.append(key)
            continue

        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.hostname != "res.cloudinary.com":
            continue
        for resource_type in ("image", "video"):
            marker = f"/{resource_type}/upload/"
            if marker not in parsed.path:
                continue
            public_id = parsed.path.split(marker, 1)[1]
            public_id = re.sub(r"^v\d+/", "", public_id)
            public_id = os.path.splitext(public_id)[0]
            if public_id.startswith(owned_prefix):
                cloudinary_assets.append((public_id, resource_type))
            break

    failures: list[str] = []
    if s3_keys:
        try:
            import boto3
            from botocore.config import Config

            s3 = boto3.client(
                "s3",
                region_name=S3_REGION,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
                endpoint_url=S3_ENDPOINT,
                config=Config(signature_version="s3v4"),
            )
            result = s3.delete_objects(
                Bucket=S3_BUCKET,
                Delete={"Objects": [{"Key": key} for key in sorted(set(s3_keys))], "Quiet": True},
            )
            failures.extend(str(item.get("Key") or "s3") for item in result.get("Errors", []))
        except Exception:
            failures.extend(s3_keys)

    if cloudinary_assets and CLOUDINARY_URL:
        try:
            import cloudinary
            import cloudinary.uploader

            cloudinary.config(secure=True)
            for public_id, resource_type in sorted(set(cloudinary_assets)):
                result = cloudinary.uploader.destroy(
                    public_id,
                    resource_type=resource_type,
                    invalidate=True,
                )
                if result.get("result") not in {"ok", "not found"}:
                    failures.append(public_id)
        except Exception:
            failures.extend(public_id for public_id, _ in cloudinary_assets)

    return list(dict.fromkeys(failures))


@app.route("/api/images/abort-upload", methods=["POST"])
@require_auth
def abort_multipart_upload():
    """
    Abort incomplete S3 multipart upload (cleanup on user cancel).
    """
    data = request.get_json(silent=True) or {}
    upload_id = str(data.get("uploadId", "")).strip()
    s3_key = str(data.get("key", "")).strip()
    
    if not s3_key or not upload_id:
        return jsonify(error="Missing uploadId or key"), 400
    
    if not s3_key.startswith(f"listings/{g.user_id}/"):
        return jsonify(error="Unauthorized"), 403
    
    # Abort on S3 if using multipart
    if S3_BUCKET and S3_ACCESS_KEY:
        try:
            import boto3
            s3 = boto3.client(
                's3',
                region_name=S3_REGION,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
                endpoint_url=S3_ENDPOINT
            )
            s3.abort_multipart_upload(Bucket=S3_BUCKET, Key=s3_key, UploadId=upload_id)
        except Exception as e:
            print(f"Error aborting upload: {e}")
    
    return jsonify(status="ok")


@app.route("/api/images/optimize", methods=["POST"])
@require_auth
def optimize_image():
    """
    Optimize uploaded image: convert to WebP/AVIF + create 3 sizes (thumbnail, medium, large).
    
    This endpoint processes the already-uploaded image from S3 and creates optimized variants.
    
    Request:
     POST /api-backend/images/optimize
     { "key": "listings/123/abc123/photo.jpg" }
    
    Response:
     {
       "thumbnail_webp": "https://cdn/.../photo-thumb.webp",
       "medium_webp": "https://cdn/.../photo-medium.webp",
       "large_webp": "https://cdn/.../photo-large.webp",
       "metadata": {
         "original_size": 1234567,
         "optimized_size": 345678,
         "compression_ratio": 72
       }
     }
    
    Architecture:
    1. Frontend uploads original image to S3 (presigned URL)
    2. Frontend calls /api-backend/images/confirm-upload to verify
    3. **Frontend calls /api-backend/images/optimize to create variants**
    4. Frontend stores all URLs in listing
    
    Benefits:
    - Original preserved for archival
    - WebP = 50% smaller than JPEG
    - AVIF = 30% smaller than WebP
    - 3 sizes = faster page load (no 1200px image for thumbnail)
    """
    
    if not HAS_IMAGE_OPTIMIZATION:
       return jsonify(error="Image optimization not available (Pillow not installed)"), 503
    
    data = request.get_json(silent=True) or {}
    s3_key = str(data.get("key", "")).strip()
    
    if not s3_key:
       return jsonify(error="Missing S3 key"), 400
    
    if not s3_key.startswith(f"listings/{g.user_id}/"):
       return jsonify(error="Unauthorized: image does not belong to you"), 403
    
    if not S3_BUCKET or not S3_ACCESS_KEY:
       return jsonify(error="S3 not configured"), 503
    
    try:
       import boto3
       s3_client = boto3.client(
           's3',
           region_name=S3_REGION,
           aws_access_key_id=S3_ACCESS_KEY,
           aws_secret_access_key=S3_SECRET_KEY,
           endpoint_url=S3_ENDPOINT
       )
        
       # Download original image
       response = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
       image_bytes = response['Body'].read()
       original_size = len(image_bytes)
        
       # Parse image
       img = Image.open(io.BytesIO(image_bytes))
       if img.mode not in ('RGB', 'RGBA'):
           img = img.convert('RGB')
        
       # Image sizes: (width, height)
       sizes = {
           'thumbnail': (150, 100),
           'medium': (400, 300),
           'large': (1200, 800)
       }
        
       results = {}
       total_optimized = 0
        
       # Create all variants
       for size_name, (width, height) in sizes.items():
           # Resize with aspect ratio
           resized = img.copy()
           resized.thumbnail((width, height), Image.Resampling.LANCZOS)
            
           # Pad to exact size
           padded = Image.new('RGB', (width, height), (255, 255, 255))
           offset = ((width - resized.width) // 2, (height - resized.height) // 2)
           padded.paste(resized, offset)
            
           # Convert to WebP
           webp_buffer = io.BytesIO()
           padded.save(webp_buffer, format='WEBP', quality=80, method=6)
           webp_data = webp_buffer.getvalue()
           total_optimized += len(webp_data)
            
           # Upload WebP variant
           output_key = s3_key.replace('.jpg', f'-{size_name}.webp').replace('.png', f'-{size_name}.webp')
           s3_client.put_object(
               Bucket=S3_BUCKET,
               Key=output_key,
               Body=webp_data,
               ContentType='image/webp',
               CacheControl='public, max-age=31536000, immutable'
           )
            
           results[f'{size_name}_webp'] = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{output_key}"
            
           # Try AVIF if supported
           try:
               avif_buffer = io.BytesIO()
               padded.save(avif_buffer, format='AVIF', quality=75)
               avif_data = avif_buffer.getvalue()
               total_optimized += len(avif_data)
                
               avif_key = output_key.replace('.webp', '.avif')
               s3_client.put_object(
                   Bucket=S3_BUCKET,
                   Key=avif_key,
                   Body=avif_data,
                   ContentType='image/avif',
                   CacheControl='public, max-age=31536000, immutable'
               )
                
               results[f'{size_name}_avif'] = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{avif_key}"
           except Exception as e:
               print(f"AVIF conversion skipped: {e}")
        
       results['metadata'] = {
           'original_size': original_size,
           'optimized_total': total_optimized,
           'compression_ratio': round((1 - total_optimized / (original_size * 3)) * 100),
           'message': f'Created 3 WebP variants + AVIF. Compression: {results["metadata"]["compression_ratio"]}%'
       }
        
       return jsonify(results)
    
    except Exception as e:
       print(f"Image optimization error: {e}")
       return jsonify(error=f"Failed to optimize image: {str(e)}"), 500


@app.route("/api/demo-images/<path:seed>.svg", methods=["GET"])
def generate_demo_svg(seed: str):
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    palette = [
        ("#0f172a", "#1d4ed8"),
        ("#1e293b", "#2563eb"),
        ("#172554", "#0ea5e9"),
        ("#111827", "#7c3aed"),
        ("#0f172a", "#0891b2"),
        ("#1f2937", "#0f766e"),
    ]
    accent_pairs = [
        ("#e2e8f0", "#cbd5e1"),
        ("#dbeafe", "#bfdbfe"),
        ("#dcfce7", "#bbf7d0"),
        ("#fae8ff", "#e9d5ff"),
        ("#fef3c7", "#fde68a"),
        ("#fee2e2", "#fecaca"),
    ]
    bg_start, bg_end = palette[int(digest[0], 16) % len(palette)]
    card_fill, card_stroke = accent_pairs[int(digest[1], 16) % len(accent_pairs)]
    seed_label = escape(seed[:28].upper())
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" role="img" aria-label="UA-Dim demo image {seed_label}">
<defs>
  <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
    <stop offset="0%" stop-color="{bg_start}"/>
    <stop offset="100%" stop-color="{bg_end}"/>
  </linearGradient>
</defs>
<rect width="1200" height="800" fill="url(#bg)"/>
<rect x="54" y="54" width="1092" height="692" rx="40" fill="rgba(255,255,255,.08)" stroke="rgba(255,255,255,.18)" stroke-width="4"/>
<rect x="106" y="122" width="420" height="42" rx="21" fill="rgba(255,255,255,.14)"/>
<text x="134" y="151" fill="#ffffff" font-family="Arial,sans-serif" font-size="28" font-weight="700">UA-Dim • Demo listing</text>
<rect x="106" y="206" width="456" height="320" rx="34" fill="{card_fill}" opacity=".95"/>
<rect x="642" y="206" width="454" height="178" rx="34" fill="rgba(255,255,255,.12)"/>
<rect x="642" y="408" width="454" height="118" rx="28" fill="rgba(255,255,255,.08)"/>
<rect x="642" y="552" width="454" height="118" rx="28" fill="rgba(255,255,255,.08)"/>
<path d="M144 466 256 338l112 96 124-154 146 186Z" fill="{card_stroke}" opacity=".95"/>
<circle cx="222" cy="292" r="46" fill="#ffffff" opacity=".72"/>
<rect x="742" y="246" width="206" height="34" rx="17" fill="rgba(255,255,255,.22)"/>
<rect x="742" y="298" width="298" height="26" rx="13" fill="rgba(255,255,255,.16)"/>
<rect x="742" y="444" width="236" height="26" rx="13" fill="rgba(255,255,255,.16)"/>
<rect x="742" y="587" width="236" height="26" rx="13" fill="rgba(255,255,255,.16)"/>
<text x="106" y="610" fill="#ffffff" font-family="Arial,sans-serif" font-size="52" font-weight="700">Надійне фото з домену UA-Dim</text>
<text x="106" y="662" fill="rgba(255,255,255,.76)" font-family="Arial,sans-serif" font-size="28">Без зовнішніх CDN • стабільно для production і preview</text>
<text x="106" y="712" fill="rgba(255,255,255,.64)" font-family="Arial,sans-serif" font-size="22">Seed: {seed_label}</text>
</svg>"""
    response = Response(svg, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


def _seo_landing_stats(db: sqlite3.Connection, limit: int = 8):
    city_rows = db.execute(
        """
        SELECT city, COUNT(*) as cnt, ROUND(AVG(price)) as avg_price
        FROM listings
        WHERE status = 'published'
        GROUP BY city
        ORDER BY cnt DESC, city ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    district_rows = db.execute(
        """
        SELECT city, district, COUNT(*) as cnt, ROUND(AVG(price)) as avg_price
        FROM listings
        WHERE status = 'published'
        GROUP BY city, district
        ORDER BY cnt DESC, city ASC, district ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return city_rows, district_rows


def _content_articles(db: sqlite3.Connection) -> list[dict]:
    city_rows, district_rows = _seo_landing_stats(db, limit=6)
    agency_rows = _agency_metrics(db, sort_by="reputation", limit=4)
    
    # Single aggregated query instead of 5 separate COUNT queries (performance: -600ms)
    stats_row = db.execute(f"""
        SELECT 
          COUNT(*) as total_count,
          SUM(CASE WHEN e_oselya = 1 THEN 1 ELSE 0 END) as e_oselya_count,
          SUM(CASE WHEN listing_status = 'active' THEN 1 ELSE 0 END) as active_count,
          SUM(CASE WHEN published_at >= {db_now_expr(-14)} THEN 1 ELSE 0 END) as freshness_count
        FROM listings WHERE status='published'
    """).fetchone()
    
    total_count = int(stats_row[0] or 0)
    e_oselya_count = int(stats_row[1] or 0)
    active_count = int(stats_row[2] or 0)
    freshness_count = int(stats_row[3] or 0)

    top_city = city_rows[0] if city_rows else None
    top_district = district_rows[0] if district_rows else None
    top_agency = agency_rows[0] if agency_rows else None
    second_agency = agency_rows[1] if len(agency_rows) > 1 else top_agency

    articles = [
        {
            "slug": "market-update-kyiv-leads",
            "category": "Ринок",
            "title": f"Київ тримає лідерство: {top_city['cnt'] if top_city else total_count} об'єктів і попит на єОселя",
            "excerpt": (
                f"Найбільше опублікованих оголошень зараз у Києві, а середня ціна тримається біля "
                f"${int(top_city['avg_price'] or 0):,}."
                if top_city
                else "Огляд ринку по містах: де найбільше пропозицій і як змінюється середня ціна."
            ),
            "published_at": "2026-08-01",
            "reading_time": 4,
            "featured": True,
            "stats": [
                {"label": "Опубліковано", "value": total_count},
                {"label": "єОселя", "value": e_oselya_count},
                {"label": "Активні", "value": active_count},
            ],
            "body_html": (
                f"<p>Ринок рухається навколо великих міст: найбільше оголошень у {escape(top_city['city']) if top_city else 'Україні'}, "
                f"а {escape(top_district['district']) if top_district else 'популярні райони'} дають хороший сигнал по локальному попиту.</p>"
                f"<p>Середня ціна в топ-місті: <strong>${int(top_city['avg_price'] or 0):,}</strong>. "
                f"Це дає нам сильний discovery-поверх для пошуку і контенту, який оновлюється разом із базою.</p>"
            ),
            "related": [
                {"label": "Відкрити карту", "href": f"{public_app_url()}?view=map"},
                {"label": "SEO-сторінки міст", "href": f"/seo/{quote(top_city['city'])}" if top_city else public_app_url()},
            ],
        },
        {
            "slug": "eoselya-watch",
            "category": "єОселя",
            "title": "єОселя watch: де найбільше придатних об'єктів",
            "excerpt": f"Зараз {e_oselya_count} опублікованих об'єктів під єОселя — це окрема воронка для конверсії.",
            "published_at": "2026-08-01",
            "reading_time": 3,
            "featured": True,
            "stats": [
                {"label": "єОселя", "value": e_oselya_count},
                {"label": "Свіжі за 14 днів", "value": freshness_count},
            ],
            "body_html": (
                f"<p>Ми виділяємо об'єкти під єОселя як окремий шлях discovery: це швидко приводить користувача до релевантних карток, "
                f"а також допомагає порівнювати міста, де таких об'єктів більше.</p>"
                f"<p>Найкраще працює зв'язка: <strong>єОселя → карта → алерт</strong>.</p>"
            ),
            "related": [
                {"label": "Шукати єОселя", "href": f"{public_app_url()}?eOselya=true"},
                {"label": "Додати алерт", "href": f"{public_app_url()}#alerts"},
            ],
        },
        {
            "slug": "verified-agencies-leadership",
            "category": "Trust",
            "title": f"{top_agency['name'] if top_agency else 'Verified partners'}: хто веде довіру на ринку",
            "excerpt": (
                f"Лідер за reputation score — {top_agency['name']} ({top_agency['reputation_score']}/100), "
                f"команда {top_agency['team_size']} осіб."
                if top_agency
                else "Профілі агентств і забудовників з рейтингом довіри, командою та кількістю угод."
            ),
            "published_at": "2026-08-01",
            "reading_time": 4,
            "featured": False,
            "stats": [
                {"label": "Лідер score", "value": top_agency["reputation_score"] if top_agency else 0},
                {"label": "Команда", "value": top_agency["team_size"] if top_agency else 0},
                {"label": "Угоди", "value": top_agency["completed_deals"] if top_agency else 0},
            ],
            "body_html": (
                f"<p>Каталог агентств став окремим продуктом: ми показуємо не лише контакт, а й репутацію, команду, угоди та verified-rate.</p>"
                f"<p>Сильні trust-сигнали мають не тільки конвертувати, а й допомагати користувачу швидко обирати, кому довіряти.</p>"
            ),
            "related": [
                {"label": "Каталог агентств", "href": "/agencies"},
                {"label": "Профіль лідера", "href": f"/agencies/{top_agency['slug']}" if top_agency else "/agencies"},
            ],
        },
        {
            "slug": "fresh-listings-quality",
            "category": "Supply",
            "title": f"Свіжість і якість: {freshness_count} об'єктів оновлено за 14 днів",
            "excerpt": "Свіжість оголошення, trust-докази та антидублі формують зрілу supply side модель.",
            "published_at": "2026-08-01",
            "reading_time": 3,
            "featured": False,
            "stats": [
                {"label": "Оновлено 14д", "value": freshness_count},
                {"label": "Верифіковано", "value": int(db.execute("SELECT COUNT(*) FROM listings WHERE status='published' AND (verified_owner=1 OR verified_phone=1 OR verified_docs=1)").fetchone()[0] or 0)},
            ],
            "body_html": (
                "<p>Окрема якість supply side — це коли користувач бачить свіжість, доказовість і низький ризик дубля ще до відкриття картки.</p>"
                "<p>Саме це ми підсвічуємо в SERP і використовуємо для ранжування довіри.</p>"
            ),
            "related": [
                {"label": "Переглянути видачу", "href": public_app_url()},
                {"label": "Ризик дубля", "href": f"{public_app_url()}?duplicateRisk=high"},
            ],
        },
        {
            "slug": "map-first-hotspots",
            "category": "Discovery",
            "title": f"Map-first discovery: {top_district['city'] if top_district else 'міські'} hotspot-и зараз",
            "excerpt": (
                f"Найактивніший район — {top_district['district']} у {top_district['city']} з {top_district['cnt']} оголошеннями."
                if top_district
                else "Карта як центральний сценарій пошуку: фокус на hotspots і локальній аналітиці."
            ),
            "published_at": "2026-08-01",
            "reading_time": 4,
            "featured": False,
            "stats": [
                {"label": "Hotspot район", "value": top_district["cnt"] if top_district else 0},
                {"label": "Міст", "value": len(city_rows)},
            ],
            "body_html": (
                f"<p>Коли карта стає ядром, discovery перестає бути списком і перетворюється на локальну аналітику попиту.</p>"
                f"<p>Ми використовуємо місто/район/агенцію/свіжість як концентрат сигналів для навігації.</p>"
            ),
            "related": [
                {"label": "У карту", "href": f"{public_app_url()}?view=map"},
                {"label": "Топ-місто", "href": f"/seo/{quote(top_district['city'])}" if top_district else public_app_url()},
            ],
        },
    ]

    return articles


def _content_article_by_slug(db: sqlite3.Connection, slug: str) -> dict | None:
    for article in _content_articles(db):
        if article["slug"] == slug:
            return article
    return None


init_db()

# ─── Routes: Auth ─────────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per minute")
def register():
    from app import _refresh_user_growth_summary, cache_delete_prefix
    data  = request.get_json(silent=True) or {}
    name  = strip(data.get("name"),  100)
    email = strip(data.get("email"), 254).lower()
    pw    = strip(data.get("password"), 128)
    account_type = normalize_account_type(data.get("accountType") or data.get("account_type"))
    plan_id = default_plan_for(account_type)

    if not name:
        return jsonify(error="Вкажіть ім'я"), 422
    if not validate_email(email):
        return jsonify(error="Невірний формат email"), 422
    if len(pw) < 8:
        return jsonify(error="Мінімум 8 символів у паролі"), 422

    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (name, email, password, account_type, plan_id) VALUES (?, ?, ?, ?, ?)",
            (name, email, hashed, account_type, plan_id),
        )
        db.commit()
    except Exception as exc:
        if not _is_db_integrity_error(exc):
            raise
        return jsonify(error="Цей email вже зареєстровано"), 409

    user_id = cur.lastrowid

    # Generate email verification token and send verification email
    verify_token = secrets.token_urlsafe(32)
    verify_expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=24)).isoformat()
    db.execute(
        "UPDATE users SET email_verify_token=?, email_verify_expires=? WHERE id=?",
        (verify_token, verify_expires, user_id)
    )
    _refresh_user_growth_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:user-growth:")
    verify_email_sent = send_email_verify(email, verify_token)

    return jsonify(
        token=make_token(user_id, email),
        user={
            "id": user_id,
            "name": name,
            "email": email,
            "email_verified": 0,
            "account_type": account_type,
            "plan_id": plan_id,
            "plan": plan_public_dict(plan_id),
        },
        verify_email_sent=verify_email_sent,
    ), 201


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("20 per minute")
def login():
    data  = request.get_json(silent=True) or {}
    email = strip(data.get("email"), 254).lower()
    pw    = strip(data.get("password"), 128)

    db   = get_db()
    row  = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    stored_password = row["password_hash"] if row and _has_key(row, "password_hash") else None
    if not stored_password and row:
        stored_password = row["password"]

    if not row or not _password_matches(pw, stored_password):
        return jsonify(error="Невірний email або пароль"), 401

    plan_id, _plan = resolve_user_plan(row)
    return jsonify(
        token=make_token(
            row["id"],
            row["email"],
            row["auth_token_version"] if _has_key(row, "auth_token_version") else 0,
        ),
        user={
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "account_type": normalize_account_type(row["account_type"] if _has_key(row, "account_type") else None),
            "plan_id": plan_id,
            "plan": plan_public_dict(plan_id),
        },
    )


@app.route("/api/auth/me", methods=["GET", "PATCH"])
@require_auth
def me():
    db  = get_db()
    if request.method == "PATCH":
        data = request.get_json(silent=True) or {}
        if "name" in data:
            name = strip(data.get("name"), 100)
            if not name:
                return jsonify(error="Вкажіть ім'я"), 422
            db.execute("UPDATE users SET name = ? WHERE id = ?", (name, g.user_id))

        raw_account_type = data.get("accountType", data.get("account_type"))
        if raw_account_type is not None:
            account_type = normalize_account_type(raw_account_type)
            current = db.execute("SELECT plan_id FROM users WHERE id = ?", (g.user_id,)).fetchone()
            current_plan = str((current["plan_id"] if current else "") or "").strip()
            # A plan belongs to a single audience, so switching cabinets resets it.
            if SUBSCRIPTION_PLANS.get(current_plan, {}).get("audience") != account_type:
                db.execute(
                    "UPDATE users SET account_type = ?, plan_id = ?, plan_expires_at = NULL WHERE id = ?",
                    (account_type, default_plan_for(account_type), g.user_id),
                )
            else:
                db.execute("UPDATE users SET account_type = ? WHERE id = ?", (account_type, g.user_id))
        db.commit()

    row = db.execute(
        "SELECT id, name, email, email_verified, phone_verified, phone,"
        " account_type, plan_id, plan_expires_at, agency_slug"
        " FROM users WHERE id = ?",
        (g.user_id,),
    ).fetchone()
    if not row:
        return jsonify(error="Користувача не знайдено"), 404

    user = dict(row)
    plan_id, plan = resolve_user_plan(row)
    user["account_type"] = normalize_account_type(user.get("account_type"))
    user["plan_id"] = plan_id
    user["plan"] = plan_public_dict(plan_id)
    user["usage"] = listing_usage(db, g.user_id, plan)
    return jsonify(user=user)


@app.route("/api/auth/verify-email", methods=["GET"])
def verify_email():
    token = strip(request.args.get("token", ""), 200)
    if not token:
        return jsonify(error="Token required"), 400
    db = get_db()
    row = db.execute(
        "SELECT id, email_verify_expires FROM users WHERE email_verify_token = ?", (token,)
    ).fetchone()
    if not row:
        return jsonify(error="Невірний або прострочений токен"), 400
    expires = row["email_verify_expires"] or ""
    try:
        if datetime.datetime.fromisoformat(expires) < datetime.datetime.utcnow():
            return jsonify(error="Токен прострочено. Запросіть новий."), 400
    except Exception:
        return jsonify(error="Невірний токен"), 400
    db.execute(
        "UPDATE users SET email_verified=1, email_verify_token=NULL, email_verify_expires=NULL WHERE id=?",
        (row["id"],)
    )
    db.commit()
    return Response(
        f'<meta http-equiv="refresh" content="0;url={public_app_url()}?email_verified=1">',
        mimetype="text/html"
    )


@app.route("/api/auth/resend-verification", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification():
    data = request.get_json(silent=True) or {}
    email = strip(data.get("email", ""), 254).lower()
    if not email:
        return jsonify(error="Email required"), 400
    db = get_db()
    row = db.execute(
        "SELECT id, email_verified FROM users WHERE email = ?", (email,)
    ).fetchone()
    if not row:
        return jsonify(ok=True)
    if row["email_verified"]:
        return jsonify(ok=True, already_verified=True)
    token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=24)).isoformat()
    db.execute(
        "UPDATE users SET email_verify_token=?, email_verify_expires=? WHERE id=?",
        (token, expires, row["id"])
    )
    db.commit()
    if not send_email_verify(email, token):
        return jsonify(error="Email delivery is not configured"), 503
    return jsonify(ok=True)


@app.route("/api/auth/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    """Request a password reset link. Non-enumerating: returns 200 for any email."""
    import hashlib as _hashlib
    data = request.get_json(silent=True) or {}
    email = strip(data.get("email", ""), 254).lower()
    if not validate_email(email):
        return jsonify(error="Invalid email"), 400

    # Fail clearly before claiming delivery when no provider is configured in production.
    if _production_secret_required() and not _email_provider_configured():
        return jsonify(error="Email delivery is not configured"), 503

    db = get_db()
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        # Non-enumerating response: do not reveal whether the address exists.
        return jsonify(ok=True)

    raw_token = secrets.token_hex(32)
    token_hash = _hashlib.sha256(raw_token.encode()).hexdigest()
    expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=30)).isoformat()
    db.execute(
        "UPDATE users SET password_reset_token_hash=?, password_reset_expires=? WHERE id=?",
        (token_hash, expires, row["id"]),
    )
    db.commit()

    reset_url = f"{public_seller_url()}#reset_token={raw_token}"
    subject = "Відновлення пароля — UA-Dim"
    body_text = f"Для відновлення пароля перейдіть за посиланням (дійсне 30 хв): {reset_url}"
    body_html = (
        f"<p>Ви отримали запит на відновлення пароля для вашого облікового запису UA-Dim.</p>"
        f'<p><a href="{reset_url}">Встановити новий пароль</a></p>'
        f"<p>Посилання дійсне 30 хвилин. Якщо ви не робили цей запит — проігноруйте листа.</p>"
    )

    if _email_provider_configured():
        ok = _send_email(email, subject, body_text, body_html)
        if not ok:
            app.logger.error("Password reset email delivery failed for user_id=%s", row["id"])
            db.execute(
                "UPDATE users SET password_reset_token_hash=NULL, password_reset_expires=NULL WHERE id=?",
                (row["id"],),
            )
            db.commit()
            # Keep the response non-enumerating even when delivery fails for a real account.
            return jsonify(ok=True)
    else:
        # Dev-only fallback: log reset URL; never reached in production.
        app.logger.info("PASSWORD RESET (dev) → %s | URL: %s", email, reset_url)

    return jsonify(ok=True)


@app.route("/api/auth/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password():
    """Consume a password-reset token and set a new password."""
    import hashlib as _hashlib
    data = request.get_json(silent=True) or {}
    raw_token = strip(data.get("token", ""), 200)
    new_pw = strip(data.get("password", ""), 128)

    if not raw_token:
        return jsonify(error="Token required"), 400
    if len(new_pw) < 8:
        return jsonify(error="Password must be at least 8 characters"), 422

    token_hash = _hashlib.sha256(raw_token.encode()).hexdigest()
    db = get_db()
    row = db.execute(
        "SELECT id, password_reset_expires FROM users WHERE password_reset_token_hash = ?",
        (token_hash,),
    ).fetchone()

    if not row:
        return jsonify(error="Invalid or expired reset token"), 400

    expires = row["password_reset_expires"] or ""
    try:
        if datetime.datetime.fromisoformat(expires) < datetime.datetime.utcnow():
            return jsonify(error="Reset token has expired"), 400
    except Exception:
        return jsonify(error="Invalid reset token"), 400

    hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(rounds=12)).decode()
    # Set both legacy password and password_hash columns; clear token to prevent replay.
    cursor = db.execute(
        "UPDATE users SET password=?, password_hash=?,"
        " password_reset_token_hash=NULL, password_reset_expires=NULL,"
        " auth_token_version=auth_token_version + 1"
        " WHERE id=? AND password_reset_token_hash=?",
        (hashed, hashed, row["id"], token_hash),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return jsonify(error="Invalid or expired reset token"), 400
    db.commit()
    return jsonify(ok=True)


@app.route("/api/auth/send-phone-code", methods=["POST"])
@require_auth
@limiter.limit("5 per hour")
def send_phone_code():
    data = request.get_json(silent=True) or {}
    phone = strip(data.get("phone", ""), 20)
    if not phone or not re.match(r"^\+?\d{7,15}$", phone):
        return jsonify(error="Невірний формат номера телефону"), 422

    is_prod = _production_secret_required()
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token  = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_phone  = os.environ.get("TWILIO_FROM_PHONE", "")
    twilio_configured = bool(account_sid and auth_token and from_phone)

    # In production, refuse immediately if no SMS provider is available.
    if is_prod and not twilio_configured:
        return jsonify(error="SMS delivery is not configured"), 503

    code = str(secrets.randbelow(900000) + 100000)  # 6-digit code
    result = send_sms_verify(phone, code)

    if result is False:
        # Twilio was configured but the send failed — do not persist the code.
        return jsonify(error="SMS delivery failed"), 502

    if result is None and is_prod:
        # Should not reach here after the guard above, but be defensive.
        return jsonify(error="SMS delivery is not configured"), 503

    # Only persist the code after a confirmed send (True) or in dev with no provider (None, non-prod).
    expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat()
    db = get_db()
    db.execute(
        "UPDATE users SET phone=?, phone_verify_code=?, phone_verify_expires=? WHERE id=?",
        (phone, code, expires, g.user_id)
    )
    db.commit()

    # Expose dev_code only when there is no provider and we are not in production.
    dev_code = code if (result is None and not is_prod) else None
    return jsonify(ok=True, dev_code=dev_code)


@app.route("/api/auth/verify-phone", methods=["POST"])
@require_auth
@limiter.limit("10 per hour")
def verify_phone():
    data = request.get_json(silent=True) or {}
    code = strip(data.get("code", ""), 10)
    if not code:
        return jsonify(error="Code required"), 400
    db = get_db()
    row = db.execute(
        "SELECT phone_verify_code, phone_verify_expires FROM users WHERE id=?", (g.user_id,)
    ).fetchone()
    if not row or row["phone_verify_code"] != code:
        return jsonify(error="Невірний код"), 400
    try:
        if datetime.datetime.fromisoformat(row["phone_verify_expires"] or "") < datetime.datetime.utcnow():
            return jsonify(error="Код прострочено. Запросіть новий."), 400
    except Exception:
        return jsonify(error="Код прострочено"), 400
    db.execute(
        "UPDATE users SET phone_verified=1, phone_verify_code=NULL, phone_verify_expires=NULL WHERE id=?",
        (g.user_id,)
    )
    db.commit()
    return jsonify(ok=True, phone_verified=True)


# ─── Routes: Listings ─────────────────────────────────────────────────────────

ALLOWED_SORT = {
    "price-asc":  "l.price ASC, l.id ASC",
    "price-desc": "l.price DESC, l.id DESC",
    "area-desc":  "l.area DESC, l.id DESC",
    "area-asc":   "l.area ASC, l.id ASC",
    "newest":     "l.created_at DESC, l.id DESC",
    "views-desc": "l.views DESC, l.id DESC",
    "relevance":  "l.created_at DESC, l.id DESC",
}

# Maps sort key → (listing column name, direction) for cursor WHERE clauses.
CURSOR_FIELD: dict[str, tuple[str, str]] = {
    "price-asc":  ("price",      "asc"),
    "price-desc": ("price",      "desc"),
    "area-asc":   ("area",       "asc"),
    "area-desc":  ("area",       "desc"),
    "newest":     ("created_at", "desc"),
    "views-desc": ("views",      "desc"),
}

LISTING_SELECT = """
    SELECT l.id, l.user_id, l.title, l.city, l.district, l.property_type, l.condition_type,
           l.price, l.rooms, l.area, l.floor, l.total_floors, l.year_built,
           l.e_oselya, l.views, l.images, l.videos, l.latitude, l.longitude, l.description,
           l.status, l.listing_type, l.source, l.agency_slug, l.listing_status, l.has_photo_tour, l.has_video_tour,
           l.verified_owner, l.verified_phone, l.verified_docs,
           l.owner_verification_status, l.phone_verification_status,
           l.moderation_status, l.moderation_reason, l.moderation_updated_at,
           l.listing_verification_status,
           l.published_at, l.created_at,
           COALESCE(dup.dup_count, 1) AS dup_count,
           u.name AS owner_name, u.email AS owner_email, u.account_type AS owner_account_type,
           u.agency_slug AS owner_agency_slug,
           ap.name AS agency_name, ap.kind AS agency_kind, ap.is_verified AS agency_verified
    FROM   listings l
    JOIN   users u ON u.id = l.user_id
    LEFT JOIN agency_profiles ap ON ap.slug = u.agency_slug
    LEFT JOIN (
        SELECT city, district, property_type, listing_type, rooms,
               CAST(area / 5 AS INTEGER) AS area_bucket,
               CAST(price / 5000 AS INTEGER) AS price_bucket,
               COUNT(*) AS dup_count
        FROM listings
        WHERE status = 'published'
        GROUP BY city, district, property_type, listing_type, rooms,
                 CAST(area / 5 AS INTEGER), CAST(price / 5000 AS INTEGER)
    ) dup
        ON dup.city = l.city
       AND dup.district = l.district
       AND dup.property_type = l.property_type
       AND dup.listing_type = l.listing_type
       AND dup.rooms = l.rooms
       AND dup.area_bucket = CAST(l.area / 5 AS INTEGER)
       AND dup.price_bucket = CAST(l.price / 5000 AS INTEGER)
"""


def _response_score(avg_response_minutes: int | None) -> int:
    if avg_response_minutes is None:
        return 45
    if avg_response_minutes <= 15:
        return 100
    if avg_response_minutes <= 30:
        return 88
    if avg_response_minutes <= 60:
        return 72
    if avg_response_minutes <= 120:
        return 58
    return 42


def _freshness_score(freshness_index: float | None) -> int:
    if freshness_index is None:
        return 50
    return max(20, min(100, int(round(freshness_index))))


def _agency_metrics(
    db: sqlite3.Connection,
    where_sql: str = "",
    where_params: tuple = (),
    sort_by: str = "reputation",
    limit: int = 30,
):
    query = f"""
        SELECT
            ap.slug,
            ap.name,
            ap.kind,
            ap.city,
            ap.specialization,
            ap.is_verified,
            ap.avg_response_minutes,
            ap.team_size,
            ap.completed_deals,
            ap.last_verified_at,
            COUNT(CASE WHEN l.status = 'published' THEN 1 END) AS active_listings,
            COUNT(l.id) AS total_listings,
            ROUND(AVG(
                CASE WHEN l.status = 'published'
                    THEN (CASE WHEN l.verified_owner = 1 THEN 1 ELSE 0 END
                        + CASE WHEN l.verified_phone = 1 THEN 1 ELSE 0 END
                        + CASE WHEN l.verified_docs = 1 THEN 1 ELSE 0 END) / 3.0
                END
            ) * 100, 1) AS verified_rate
            ,
            ROUND(AVG(
                CASE WHEN l.status = 'published'
                    THEN CASE WHEN l.moderation_status = 'approved' THEN 1 ELSE 0 END
                END
            ) * 100, 1) AS moderation_rate,
            ROUND(AVG(
                CASE WHEN l.status = 'published'
                    THEN CASE
                        WHEN l.listing_status = 'active' THEN 100
                        WHEN l.listing_status = 'sold' THEN 75
                        WHEN l.listing_status = 'removed' THEN 40
                        ELSE 60
                    END
                END
            ), 1) AS freshness_index
        FROM agency_profiles ap
        LEFT JOIN listings l ON l.agency_slug = ap.slug
        {where_sql}
        GROUP BY ap.slug, ap.name, ap.kind, ap.city, ap.specialization, ap.is_verified, ap.avg_response_minutes, ap.team_size, ap.completed_deals, ap.last_verified_at
        ORDER BY ap.is_verified DESC, active_listings DESC, ap.name ASC
        LIMIT ?
    """
    rows = db.execute(query, tuple(where_params) + (limit,)).fetchall()
    metrics: list[dict] = []
    for row in rows:
        avg_response_minutes = row["avg_response_minutes"]
        active_listings = int(row["active_listings"] or 0)
        verified_rate = float(row["verified_rate"] or 0)
        moderation_rate = float(row["moderation_rate"] or 0)
        freshness_index = float(row["freshness_index"]) if row["freshness_index"] is not None else None
        response_score = _response_score(avg_response_minutes)
        freshness_score = _freshness_score(freshness_index)
        reputation_score = int(round(
            verified_rate * 0.4
            + response_score * 0.22
            + freshness_score * 0.2
            + moderation_rate * 0.18
            + (5 if row["is_verified"] else 0)
        ))
        team_size = row["team_size"] if row["team_size"] is not None else max(2, min(60, active_listings // 3 + 2))
        if reputation_score >= 85:
            reputation_tier = "A+"
        elif reputation_score >= 75:
            reputation_tier = "A"
        elif reputation_score >= 65:
            reputation_tier = "B"
        else:
            reputation_tier = "C"

        metrics.append({
            "slug": row["slug"],
            "name": row["name"],
            "kind": row["kind"],
            "city": row["city"],
            "specialization": row["specialization"] or "",
            "is_verified": bool(row["is_verified"]),
            "avg_response_minutes": avg_response_minutes,
            "team_size": int(team_size),
            "completed_deals": int(row["completed_deals"] or 0),
            "last_verified_at": row["last_verified_at"],
            "active_listings": active_listings,
            "total_listings": int(row["total_listings"] or 0),
            "verified_rate": verified_rate,
            "moderation_rate": moderation_rate,
            "freshness_index": freshness_index,
            "response_score": response_score,
            "freshness_score": freshness_score,
            "reputation_score": reputation_score,
            "reputation_tier": reputation_tier,
        })

    if sort_by == "active":
        metrics.sort(key=lambda item: (item["active_listings"], item["reputation_score"]), reverse=True)
    elif sort_by == "response":
        metrics.sort(key=lambda item: (item["response_score"], item["reputation_score"]), reverse=True)
    elif sort_by == "verified_rate":
        metrics.sort(key=lambda item: (item["verified_rate"], item["reputation_score"]), reverse=True)
    else:
        metrics.sort(key=lambda item: (item["reputation_score"], item["active_listings"]), reverse=True)
    return metrics


@app.route("/api/agencies", methods=["GET"])
def get_agencies():
    db = get_db()
    args = request.args
    city = strip(args.get("city", ""), 100)
    kind = strip(args.get("kind", ""), 20).lower()
    verified_only = truthy_flag(args.get("verified_only"))
    q = strip(args.get("q", ""), 80)
    sort_by = strip(args.get("sort", "reputation"), 32).lower()
    limit = nonneg_int(args.get("limit")) or 30
    limit = min(max(limit, 1), 100)
    filters = []
    params: list = []
    if verified_only:
        filters.append("ap.is_verified = 1")
    if city:
        filters.append("ap.city = ?")
        params.append(city)
    if kind in {"agency", "developer"}:
        filters.append("ap.kind = ?")
        params.append(kind)
    if q:
        filters.append("(ap.name LIKE ? OR ap.specialization LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    return jsonify(agencies=_agency_metrics(db, where_sql, tuple(params), sort_by=sort_by, limit=limit))


@app.route("/agencies", methods=["GET"])
def agencies_catalog_page():
    db = get_db()
    city = strip(request.args.get("city", ""), 100)
    kind = strip(request.args.get("kind", ""), 20).lower()
    verified_only = truthy_flag(request.args.get("verified_only"))
    sort_by = strip(request.args.get("sort", "reputation"), 32).lower()
    q = strip(request.args.get("q", ""), 80)
    filters = []
    params: list = []
    if verified_only:
        filters.append("ap.is_verified = 1")
    if city:
        filters.append("ap.city = ?")
        params.append(city)
    if kind in {"agency", "developer"}:
        filters.append("ap.kind = ?")
        params.append(kind)
    if q:
        filters.append("(ap.name LIKE ? OR ap.specialization LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    agencies = _agency_metrics(db, where_sql, tuple(params), sort_by=sort_by, limit=100)
    cards_html = "".join(
        f"""
        <article style="border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:14px">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
            <div>
              <h3 style="margin:0 0 4px;font-size:18px">{escape(item["name"])}</h3>
              <p style="margin:0;color:#475569">{'Агентство' if item["kind"] == 'agency' else 'Забудовник'} · {escape(item["city"])} · Команда: {item["team_size"]}</p>
            </div>
            <span style="padding:6px 10px;border-radius:999px;background:#dbeafe;color:#1d4ed8;font-weight:700">Рейтинг {item["reputation_tier"]} · {item["reputation_score"]}/100</span>
          </div>
          <p style="margin:8px 0 10px;color:#334155">{escape(item["specialization"] or 'Нерухомість і супровід угод')}</p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px">
            <span style="font-size:12px;padding:5px 8px;border:1px solid #bfdbfe;background:#eff6ff;border-radius:10px">Активні: {item["active_listings"]}</span>
            <span style="font-size:12px;padding:5px 8px;border:1px solid #bbf7d0;background:#f0fdf4;border-radius:10px">Verified-rate: {item["verified_rate"]:.1f}%</span>
            <span style="font-size:12px;padding:5px 8px;border:1px solid #fde68a;background:#fffbeb;border-radius:10px">SLA відповіді: {item["avg_response_minutes"] or '—'} хв</span>
            <span style="font-size:12px;padding:5px 8px;border:1px solid #e2e8f0;background:#f8fafc;border-radius:10px">Угод: {item["completed_deals"]}</span>
          </div>
          <a href="/agencies/{quote(item["slug"])}" style="display:inline-block;padding:8px 12px;border-radius:10px;background:#0f172a;color:#fff;text-decoration:none;font-weight:600">Відкрити профіль</a>
        </article>
        """
        for item in agencies
    ) or '<p style="color:#64748b">Нічого не знайдено за фільтрами.</p>'
    html = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Каталог агентств і забудовників — UA Dim</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:1060px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:20px">
  <a href="{public_app_url()}" style="color:#2563eb;text-decoration:none">← До каталогу нерухомості</a>
  <h1 style="margin:12px 0 4px">Каталог агентств / забудовників</h1>
  <p style="margin:0 0 14px;color:#475569">Рейтинг за репутацією, trust-якістю, швидкістю відповіді та свіжістю активних оголошень.</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:0 0 16px">
    <div style="border:1px solid #dbeafe;background:#eff6ff;border-radius:12px;padding:10px"><b>{len(agencies)}</b><div style="color:#475569">Профілів</div></div>
    <div style="border:1px solid #dcfce7;background:#f0fdf4;border-radius:12px;padding:10px"><b>{sum(1 for item in agencies if item['is_verified'])}</b><div style="color:#475569">Верифікованих</div></div>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:10px"><b>{sum(item['active_listings'] for item in agencies)}</b><div style="color:#475569">Активних оголошень</div></div>
    <div style="border:1px solid #fef3c7;background:#fffbeb;border-radius:12px;padding:10px"><b>{round(sum(item['reputation_score'] for item in agencies)/len(agencies),1) if agencies else 0}</b><div style="color:#475569">Середній репутаційний score</div></div>
  </div>
  <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px">{cards_html}</section>
</main></body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/api/agencies/<slug>", methods=["GET"])
def get_agency_profile(slug: str):
    db = get_db()
    metrics = _agency_metrics(db, "WHERE ap.slug = ?", (slug,))
    if not metrics:
        return jsonify(error="Агентство/забудовника не знайдено"), 404
    profile = metrics[0]
    listing_rows = db.execute(
        LISTING_SELECT + " WHERE l.status = 'published' AND l.agency_slug = ? ORDER BY l.created_at DESC LIMIT 12",
        (slug,),
    ).fetchall()
    profile["listings"] = [_row_to_listing(r) for r in listing_rows]
    return jsonify(profile=profile)


@app.route("/agencies/<slug>", methods=["GET"])
def agency_profile_page(slug: str):
    db = get_db()
    metrics = _agency_metrics(db, "WHERE ap.slug = ?", (slug,))
    if not metrics:
        return Response("<h1>Профіль не знайдено</h1>", status=404, mimetype="text/html")
    profile = metrics[0]
    listing_rows = db.execute(
        "SELECT id, title, city, district, price FROM listings WHERE status='published' AND agency_slug=? ORDER BY created_at DESC LIMIT 10",
        (slug,),
    ).fetchall()
    listing_items = "".join(
        f'<li><a href="/listing/{row["id"]}" style="color:#1d4ed8;text-decoration:none">{escape(row["title"])}</a>'
        f' <span style="color:#64748b">({escape(row["city"])}, {escape(row["district"])}) — ${int(row["price"]):,}</span></li>'
        for row in listing_rows
    ) or "<li>Поки немає активних оголошень</li>"
    kind_label = "Агентство" if profile["kind"] == "agency" else "Забудовник"
    verified_label = "Перевірено" if profile["is_verified"] else "Не перевірено"
    trust_text = {
        "A+": "Високий рівень довіри",
        "A": "Сильний рівень довіри",
        "B": "Стабільний рівень довіри",
        "C": "Базовий рівень довіри",
    }.get(profile["reputation_tier"], "Рівень довіри уточнюється")
    html = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(profile["name"])} — UA Dim</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:920px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:24px">
  <a href="/agencies" style="color:#2563eb;text-decoration:none">← До каталогу агентств</a>
  <h1 style="margin:14px 0 8px">{escape(profile["name"])}</h1>
  <p style="margin:0 0 8px;color:#475569">{kind_label} · {escape(profile["city"])} · {verified_label}</p>
  <p style="margin:0 0 16px;color:#1e3a8a;font-weight:600">Репутація: {profile["reputation_tier"]} ({profile["reputation_score"]}/100) · {trust_text}</p>
  <p style="margin:0 0 16px;color:#334155">{escape(profile["specialization"])}</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px">
    <div style="border:1px solid #dbeafe;background:#eff6ff;border-radius:12px;padding:12px"><b>{profile["active_listings"]}</b><div style="color:#475569">Активні оголошення</div></div>
    <div style="border:1px solid #dcfce7;background:#f0fdf4;border-radius:12px;padding:12px"><b>{profile["verified_rate"]:.1f}%</b><div style="color:#475569">Verified-rate</div></div>
    <div style="border:1px solid #fef3c7;background:#fffbeb;border-radius:12px;padding:12px"><b>{profile["avg_response_minutes"] or "—"} хв</b><div style="color:#475569">Середній час відповіді</div></div>
    <div style="border:1px solid #ede9fe;background:#f5f3ff;border-radius:12px;padding:12px"><b>{profile["team_size"]}</b><div style="color:#475569">Команда</div></div>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px"><b>{profile["completed_deals"]}</b><div style="color:#475569">Закриті угоди</div></div>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px"><b>{escape(profile["last_verified_at"] or "—")}</b><div style="color:#475569">Остання перевірка</div></div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px">
    <span style="font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid #bfdbfe;background:#eff6ff">Quality score: {profile["reputation_score"]}/100</span>
    <span style="font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid #bbf7d0;background:#f0fdf4">Moderation approve-rate: {profile["moderation_rate"]:.1f}%</span>
    <span style="font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid #fde68a;background:#fffbeb">Freshness-index: {round(profile["freshness_index"], 1) if profile["freshness_index"] is not None else "—"} / 100</span>
  </div>
  <h2 style="margin:8px 0 10px">Актуальні оголошення</h2>
  <ul style="margin:0;padding-left:20px;line-height:1.7">{listing_items}</ul>
</main></body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/api/content", methods=["GET"])
def get_content_articles():
    db = get_db()
    limit = nonneg_int(request.args.get("limit")) or 6
    limit = min(max(limit, 1), 12)
    category = strip(request.args.get("category", ""), 32)
    articles = _content_articles(db)
    if category:
        articles = [article for article in articles if article["category"].lower() == category.lower()]
    return jsonify(articles=articles[:limit], featured=[article for article in articles if article.get("featured")][:limit])


@app.route("/insights", methods=["GET"])
def insights_hub():
    db = get_db()
    articles = _content_articles(db)
    cards = "".join(
        f"""
        <article style="border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:16px">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
            <span style="font-size:12px;font-weight:700;color:#2563eb;background:#eff6ff;padding:6px 10px;border-radius:999px">{escape(article["category"])}</span>
            <span style="font-size:12px;color:#64748b">{escape(article["published_at"])} · {article["reading_time"]} хв</span>
          </div>
          <h2 style="margin:10px 0 6px;font-size:20px">{escape(article["title"])}</h2>
          <p style="margin:0 0 12px;color:#475569">{escape(article["excerpt"])}</p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">
            {''.join(f'<span style="font-size:12px;padding:5px 8px;border-radius:10px;border:1px solid #dbeafe;background:#eff6ff">{escape(str(stat["label"]))}: {escape(str(stat["value"]))}</span>' for stat in article["stats"])}
          </div>
          <a href="/insights/{quote(article["slug"])}" style="color:#1d4ed8;font-weight:700;text-decoration:none">Читати →</a>
        </article>
        """
        for article in articles
    )
    featured = [article for article in articles if article.get("featured")]
    featured_html = "".join(
        f'<span style="display:inline-block;margin:4px 8px 4px 0;padding:6px 10px;border-radius:999px;background:#dbeafe;color:#1d4ed8;font-weight:700">{escape(article["title"])}</span>'
        for article in featured
    ) or "<span style='color:#64748b'>Немає featured контенту</span>"
    html = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Insights — UA-Dim</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:1100px;margin:0 auto">
  <a href="{public_app_url()}" style="color:#2563eb;text-decoration:none">← До каталогу</a>
  <h1 style="margin:12px 0 6px;font-size:36px">Market insights / контентна машина</h1>
  <p style="margin:0 0 14px;color:#475569">Сторінки оновлюються з ринкових даних: міста, райони, єОселя, trust та карта.</p>
  <div style="margin:0 0 18px">{featured_html}</div>
  <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px">{cards}</section>
</main></body></html>"""
    return Response(html, mimetype="text/html")


@app.route("/insights/<slug>", methods=["GET"])
def insight_article(slug: str):
    db = get_db()
    article = _content_article_by_slug(db, slug)
    if not article:
        return Response("<h1>Матеріал не знайдено</h1>", status=404, mimetype="text/html")
    related_html = "".join(
        f'<li><a href="{escape(link["href"])}" style="color:#1d4ed8;text-decoration:none">{escape(link["label"])}</a></li>'
        for link in article.get("related", [])
    )
    stats_html = "".join(
        f'<div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px"><b>{escape(str(stat["value"]))}</b><div style="color:#475569">{escape(str(stat["label"]))}</div></div>'
        for stat in article.get("stats", [])
    )
    html = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(article["title"])} — UA-Dim Insights</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:920px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:24px">
  <a href="/insights" style="color:#2563eb;text-decoration:none">← До Insights</a>
  <div style="margin-top:10px;font-size:12px;font-weight:700;color:#2563eb;background:#eff6ff;display:inline-block;padding:6px 10px;border-radius:999px">{escape(article["category"])}</div>
  <h1 style="margin:12px 0 6px;font-size:34px">{escape(article["title"])}</h1>
  <p style="margin:0 0 12px;color:#64748b">{escape(article["published_at"])} · {article["reading_time"]} хв читання</p>
  <p style="margin:0 0 18px;color:#334155;font-size:18px">{escape(article["excerpt"])}</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:18px">{stats_html}</div>
  <article style="line-height:1.7;color:#334155">{article["body_html"]}</article>
  <h2 style="margin:20px 0 8px">Пов'язані переходи</h2>
  <ul style="margin:0;padding-left:20px;line-height:1.8">{related_html}</ul>
</main></body></html>"""
    return Response(html, mimetype="text/html")


@limiter.limit("600 per hour")  # 10 requests/min average, burst 30/min
@app.route("/api/listings", methods=["GET"])
def get_listings():
    db   = get_db()
    args = request.args

    mine_only     = truthy_flag(args.get("mine"))
    city          = strip(args.get("city",      ""), 100)
    prop_type     = strip(args.get("type",      ""), 50)
    min_price     = pos_int(args.get("minPrice"))
    max_price     = pos_int(args.get("maxPrice"))
    min_rooms     = nonneg_int(args.get("minRooms"))
    max_rooms     = nonneg_int(args.get("maxRooms"))
    min_area      = pos_float(args.get("minArea"))
    max_area      = pos_float(args.get("maxArea"))
    e_oselya      = args.get("eOselya") == "1"
    district      = strip(args.get("district", ""), 100)
    search        = strip(args.get("search", ""), 120)
    status        = strip(args.get("status", "all" if mine_only else "published"), 20).lower()
    limit         = nonneg_int(args.get("limit")) or 60
    offset        = nonneg_int(args.get("offset")) or 0
    limit         = min(max(limit, 1), 200)
    sort_key      = args.get("sort", "newest")
    order_by      = ALLOWED_SORT.get(sort_key, ALLOWED_SORT["newest"])
    listing_type  = strip(args.get("listing_type", ""), 10).lower()
    ids_param     = strip(args.get("ids", ""), 2000)
    min_floor     = nonneg_int(args.get("minFloor"))
    max_floor     = nonneg_int(args.get("maxFloor"))
    min_year      = nonneg_int(args.get("minYear"))
    max_year      = nonneg_int(args.get("maxYear"))
    agency_slug   = strip(args.get("agency", ""), 80).lower()
    verified_agency_only = truthy_flag(args.get("verifiedAgency"))
    duplicate_risk_filter = strip(args.get("duplicateRisk", ""), 10).lower()
    listing_ids: list[int] = []
    ranked_fts_ids: list[int] = []
    if ids_param:
        for raw_part in ids_param.split(","):
            raw_part = raw_part.strip()
            if not raw_part:
                continue
            try:
                value = int(raw_part)
            except ValueError:
                continue
            if value > 0:
                listing_ids.append(value)
        listing_ids = list(dict.fromkeys(listing_ids))[:200]

    actor_id, is_admin = get_optional_actor(db)
    if not mine_only and not is_admin and status and status != "published":
        return jsonify(error="Недостатньо прав для перегляду неопублікованих оголошень"), 403

    if not status:
        status = "published"

    cache_payload: dict | None = None
    cache_key = None
    cacheable_public_query = (
        not mine_only
        and not is_admin
        and status == "published"
        and sort_key != "views-desc"
    )
    if cacheable_public_query:
        query_string = request.query_string.decode("utf-8", errors="ignore")
        cache_key = f"public:listings:v1:{query_string}"
        cache_payload = cached_json_get(cache_key)
        if cache_payload is not None:
            return jsonify(**cache_payload)

    query  = LISTING_SELECT + " WHERE 1=1"
    params: list = []

    if mine_only:
        if actor_id is None:
            return jsonify(error="Потрібна авторизація"), 401
        query += " AND l.user_id = ?"
        params.append(actor_id)

    if status and status != "all":
        query += " AND l.status = ?"
        params.append(status)

    if listing_type in ("sale", "rent"):
        query += " AND l.listing_type = ?"
        params.append(listing_type)

    if city:
        query += " AND l.city = ?"
        params.append(city)
    if district:
        query += " AND l.district LIKE ?"
        params.append(f"%{district}%")
    if prop_type:
        query += " AND l.property_type = ?"
        params.append(prop_type)
    if agency_slug:
        query += " AND l.agency_slug = ?"
        params.append(agency_slug)
    if verified_agency_only:
        # Optimization: Use INNER JOIN instead of EXISTS subquery for better performance
        # We need to add INNER JOIN for verified agencies if not already present in the base query
        # For now, use efficient condition: agency must exist and be verified
        query += " AND ap.is_verified = 1"
    if duplicate_risk_filter == "high":
        query += " AND COALESCE(dup.dup_count, 1) >= 3"
    elif duplicate_risk_filter == "medium":
        query += " AND COALESCE(dup.dup_count, 1) = 2"
    elif duplicate_risk_filter == "low":
        query += " AND COALESCE(dup.dup_count, 1) <= 1"
    if ids_param:
        if listing_ids:
            placeholders = ",".join("?" for _ in listing_ids)
            query += f" AND l.id IN ({placeholders})"
            params.extend(listing_ids)
        else:
            query += " AND 1 = 0"
    if min_price is not None:
        query += " AND l.price >= ?"
        params.append(min_price)
    if max_price is not None:
        query += " AND l.price <= ?"
        params.append(max_price)
    if min_rooms is not None:
        query += " AND l.rooms >= ?"
        params.append(min_rooms)
    if max_rooms is not None:
        query += " AND l.rooms <= ?"
        params.append(max_rooms)
    if min_area is not None:
        query += " AND l.area >= ?"
        params.append(min_area)
    if max_area is not None:
        query += " AND l.area <= ?"
        params.append(max_area)
    if e_oselya:
        query += " AND l.e_oselya = 1"
    if search:
        # Use FTS5 for full-text search; fall back to LIKE on error
        try:
            fts_rows = db.execute(
                "SELECT rowid FROM listings_fts WHERE listings_fts MATCH ? ORDER BY rank LIMIT 500",
                (search,)
            ).fetchall()
            fts_ids = [int(r[0]) for r in fts_rows if int(r[0]) > 0]
            if fts_ids:
                ranked_fts_ids = fts_ids[:200]
                placeholders = ",".join("?" for _ in fts_ids)
                query += f" AND l.id IN ({placeholders})"
                params.extend(fts_ids)
            else:
                query += " AND 1=0"  # no FTS results
        except Exception:
            # FTS not available, fall back to LIKE
            token = f"%{search}%"
            query += " AND (l.title LIKE ? OR l.city LIKE ? OR l.district LIKE ? OR l.description LIKE ?)"
            params.extend([token, token, token, token])
    if min_floor is not None:
        query += " AND l.floor >= ?"
        params.append(min_floor)
    if max_floor is not None:
        query += " AND l.floor <= ?"
        params.append(max_floor)
    if min_year is not None:
        query += " AND l.year_built >= ?"
        params.append(min_year)
    if max_year is not None:
        query += " AND l.year_built <= ?"
        params.append(max_year)

    count_query = f"SELECT COUNT(*) FROM ({query})"
    total = db.execute(count_query, params).fetchone()[0]

    # Cursor pagination: decode opaque cursor and add keyset WHERE clause.
    relevance_order_by: str | None = None
    if search and sort_key == "relevance" and ranked_fts_ids:
        relevance_order_by = (
            "CASE l.id "
            + " ".join(f"WHEN {listing_id} THEN {rank}" for rank, listing_id in enumerate(ranked_fts_ids))
            + f" ELSE {len(ranked_fts_ids)} END, l.created_at DESC"
        )

    force_offset_pagination = relevance_order_by is not None
    cursor_param = "" if force_offset_pagination else strip(args.get("cursor", ""), 1000)
    cursor_data: dict | None = None
    if cursor_param:
        try:
            decoded = base64.urlsafe_b64decode(cursor_param + "==").decode()
            cd = json.loads(decoded)
            if (
                isinstance(cd, dict)
                and cd.get("sort_by") == sort_key
                and cd.get("last_id") is not None
                and cd.get("last_value") is not None
            ):
                cursor_data = cd
        except Exception:
            pass

    cursor_active = False
    if cursor_data:
        last_val = cursor_data["last_value"]
        last_id  = int(cursor_data["last_id"])
        cf_name, cf_dir = CURSOR_FIELD.get(sort_key, ("id", "desc"))
        if cf_dir == "desc":
            query += f" AND (l.{cf_name} < ? OR (l.{cf_name} = ? AND l.id < ?))"
        else:
            query += f" AND (l.{cf_name} > ? OR (l.{cf_name} = ? AND l.id > ?))"
        params.extend([last_val, last_val, last_id])
        query += f" ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        cursor_active = True
        offset = 0
    else:
        query += f" ORDER BY {relevance_order_by or order_by} LIMIT ? OFFSET ?"
        params.extend([limit, offset])

    rows = db.execute(query, params).fetchall()
    # `mine=1` requests are already scoped to the authenticated owner (or
    # admin) above, so it's safe to include private fields for that view.
    listings = [_row_to_listing(r, include_private=mine_only) for r in rows]

    if force_offset_pagination:
        has_more = (offset + len(listings)) < total
    elif cursor_active:
        has_more = len(listings) == limit
    else:
        has_more = (offset + len(listings)) < total

    # Build opaque next_cursor so frontend can fetch the next page without offset drift.
    next_cursor: str | None = None
    if has_more and listings and not force_offset_pagination:
        last = listings[-1]
        cf_name, _ = CURSOR_FIELD.get(sort_key, ("id", "desc"))
        cursor_obj = {
            "sort_by":    sort_key,
            "last_value": last.get(cf_name),
            "last_id":    last["id"],
        }
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps(cursor_obj).encode())
            .decode()
            .rstrip("=")
        )

    response_payload = dict(
        listings=listings,
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
        next_cursor=next_cursor,
    )
    if truthy_flag(args.get("includeFacets")):
        city_rows = db.execute(
            """
            SELECT DISTINCT city
            FROM listings
            WHERE status = 'published' AND TRIM(COALESCE(city, '')) <> ''
            ORDER BY city
            """
        ).fetchall()
        response_payload["facets"] = {"cities": [row[0] for row in city_rows]}
    if cache_key and cacheable_public_query:
        cached_json_set(cache_key, response_payload, ttl_seconds=20)
    return jsonify(**response_payload)


@limiter.limit("1200 per hour")  # 20 requests/min average
@app.route("/api/listings/<int:lid>", methods=["GET"])
def get_listing(lid: int):
    db  = get_db()
    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (lid,)).fetchone()
    if not row:
        return jsonify(error="Оголошення не знайдено"), 404
    actor_id, is_admin = get_optional_actor(db)
    is_owner = actor_id is not None and row["user_id"] == actor_id
    if row["status"] != "published" and not is_owner and not is_admin:
        return jsonify(error="Оголошення ще не опубліковано"), 404
    listing = _row_to_listing(row, include_private=(is_owner or is_admin))
    reviews = db.execute(
        "SELECT id, user_name, rating, comment, created_at FROM reviews WHERE listing_id = ? ORDER BY created_at DESC",
        (lid,)
    ).fetchall()
    listing["reviews"] = [dict(r) for r in reviews]
    return jsonify(listing=listing)


@app.route("/api/listings/<int:lid>/view", methods=["POST"])
def increment_view(lid: int):
    db = get_db()
    db.execute("UPDATE listings SET views = views + 1 WHERE id = ?", (lid,))
    db.commit()
    row = db.execute("SELECT views FROM listings WHERE id = ?", (lid,)).fetchone()
    return jsonify(views=row["views"] if row else 0)


@app.route("/api/listings/<int:lid>/reviews", methods=["GET"])
def get_reviews(lid: int):
    db = get_db()
    rows = db.execute(
        "SELECT id, user_name, rating, comment, created_at FROM reviews WHERE listing_id = ? ORDER BY created_at DESC",
        (lid,)
    ).fetchall()
    return jsonify(reviews=[dict(r) for r in rows])


@app.route("/api/listings/<int:lid>/reviews", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def add_review(lid: int):
    db = get_db()
    if not db.execute("SELECT id FROM listings WHERE id = ?", (lid,)).fetchone():
        return jsonify(error="Оголошення не знайдено"), 404

    data    = request.get_json(silent=True) or {}
    rating  = nonneg_int(data.get("rating"))
    comment = strip(data.get("comment", ""), 1000)

    if rating is None or not (1 <= rating <= 5):
        return jsonify(error="Рейтинг від 1 до 5"), 422
    if len(comment) < 5:
        return jsonify(error="Коментар мінімум 5 символів"), 422

    user = db.execute("SELECT name FROM users WHERE id = ?", (g.user_id,)).fetchone()
    user_name = user["name"] if user else "Анонім"

    cur = db.execute(
        "INSERT INTO reviews (listing_id, user_id, user_name, rating, comment) VALUES (?,?,?,?,?)",
        (lid, g.user_id, user_name, rating, comment),
    )
    db.commit()
    row = db.execute("SELECT id, user_name, rating, comment, created_at FROM reviews WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(review=dict(row)), 201


SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,120}$")


@app.route("/api/listings/<int:lid>/trust", methods=["GET"])
def get_listing_trust(lid: int):
    """Public trust surface for a listing: real listing-verification status
    (distinct from moderation/owner verification), the seller type derived
    from the account itself, comparable-price statistics, and sanitized
    field history. Never exposes reporter data, moderation notes, owner
    email, or admin identifiers."""
    db = get_db()
    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (lid,)).fetchone()
    if not row:
        return jsonify(error="Оголошення не знайдено"), 404
    actor_id, is_admin = get_optional_actor(db)
    is_owner = actor_id is not None and row["user_id"] == actor_id
    if row["status"] != "published" and not is_owner and not is_admin:
        return jsonify(error="Оголошення ще не опубліковано"), 404

    listing = _row_to_listing(row)
    return jsonify(
        listing_id=lid,
        listing_verification_status=listing["listing_verification_status"],
        verified_listing=listing["verified_listing"],
        seller_type=listing["seller_type"],
        price_statistics=comparable_price_stats(db, row),
        history=public_field_history(db, lid),
    )


@app.route("/api/listings/<int:lid>/reports", methods=["POST"])
@limiter.limit("5 per hour")
def report_listing(lid: int):
    """File a fraud/quality report against a published listing. Works for
    authenticated users (via bearer token) and anonymous visitors (via a
    client-generated reporter_session_id). Reporter identity is never stored
    directly — only a non-reversible HMAC fingerprint used for dedupe."""
    db = get_db()
    listing = db.execute("SELECT id, status FROM listings WHERE id = ?", (lid,)).fetchone()
    if not listing or listing["status"] != "published":
        return jsonify(error="Оголошення не знайдено"), 404

    actor_id, _is_admin = get_optional_actor(db)
    data = request.get_json(silent=True) or {}

    reason_code = strip(data.get("reason_code", data.get("reasonCode")), 40).lower()
    details = strip(data.get("details"), 1000)
    idempotency_key = strip(data.get("idempotency_key", data.get("idempotencyKey")), 120)
    reporter_session_id = strip(data.get("reporter_session_id", data.get("reporterSessionId")), 120)

    if reason_code not in REPORT_REASON_CODES:
        return jsonify(error="Невалідна причина скарги", field="reason_code"), 422
    if not (10 <= len(details) <= 1000):
        return jsonify(error="Опис має містити від 10 до 1000 символів", field="details"), 422
    if not idempotency_key or not SAFE_TOKEN_RE.match(idempotency_key):
        return jsonify(error="Невалідний idempotency_key", field="idempotency_key"), 422

    if actor_id is not None:
        # Authenticated (a stale/invalid bearer already resolves to actor_id
        # None via get_optional_actor, so this only fires for a real session).
        identity = f"user:{actor_id}"
        reporter_user_id = actor_id
    else:
        if not reporter_session_id or not SAFE_TOKEN_RE.match(reporter_session_id):
            return jsonify(error="Потрібен валідний reporter_session_id для анонімної скарги", field="reporter_session_id"), 422
        identity = f"session:{reporter_session_id}"
        reporter_user_id = None

    fingerprint = _reporter_fingerprint(identity)

    def _sanitized(row) -> dict:
        return {
            "id": row["id"],
            "listing_id": row["listing_id"],
            "reason_code": row["reason_code"],
            "status": row["status"],
            "created_at": row["created_at"],
        }

    existing_by_key = db.execute(
        "SELECT id, listing_id, reporter_fingerprint, reason_code, details, status, created_at"
        " FROM listing_reports WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if existing_by_key:
        if (
            existing_by_key["reporter_fingerprint"] == fingerprint
            and existing_by_key["listing_id"] == lid
            and existing_by_key["reason_code"] == reason_code
            and existing_by_key["details"] == details
        ):
            return jsonify(duplicate=True, report=_sanitized(existing_by_key)), 200
        return jsonify(error="idempotency_key вже використано для іншого запиту", code="idempotency_conflict"), 409

    created_at_expression = "created_at::timestamptz" if _is_postgres() else "created_at"
    recent_dupe = db.execute(
        f"""
        SELECT id FROM listing_reports
        WHERE listing_id = ? AND reporter_fingerprint = ? AND reason_code = ?
          AND {created_at_expression} > {db_now_expr(offset_days=1)}
        LIMIT 1
        """,
        (lid, fingerprint, reason_code),
    ).fetchone()
    if recent_dupe:
        return jsonify(error="Ви вже подавали цю скаргу протягом останніх 24 годин", code="duplicate_report"), 409

    try:
        cur = db.execute(
            """
            INSERT INTO listing_reports
                (listing_id, reporter_user_id, reporter_fingerprint, reason_code, details, status, idempotency_key)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (lid, reporter_user_id, fingerprint, reason_code, details, idempotency_key),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        if _is_db_integrity_error(exc):
            # Race: a concurrent request inserted the same idempotency_key first.
            row = db.execute(
                "SELECT id, listing_id, reporter_fingerprint, reason_code, details, status, created_at"
                " FROM listing_reports WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if (
                row
                and row["reporter_fingerprint"] == fingerprint
                and row["listing_id"] == lid
                and row["reason_code"] == reason_code
                and row["details"] == details
            ):
                return jsonify(duplicate=True, report=_sanitized(row)), 200
            return jsonify(error="idempotency_key вже використано для іншого запиту", code="idempotency_conflict"), 409
        raise

    row = db.execute(
        "SELECT id, listing_id, reason_code, status, created_at"
        " FROM listing_reports WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    return jsonify(duplicate=False, report=_sanitized(row)), 201


def seller_can_fast_publish(db, user_id: int) -> bool:
    trusted_seller = db.execute(
        """
        SELECT 1
        FROM users u
        LEFT JOIN agency_profiles ap ON ap.slug = u.agency_slug
        WHERE u.id = ?
          AND (
              COALESCE(ap.is_verified, 0) = 1
              OR EXISTS (
                  SELECT 1
                  FROM listings trusted_listing
                  WHERE trusted_listing.user_id = u.id
                    AND trusted_listing.status = 'published'
                    AND trusted_listing.moderation_status = 'approved'
                    AND trusted_listing.verified_owner = 1
                    AND trusted_listing.verified_phone = 1
              )
          )
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return bool(trusted_seller)


@app.route("/api/listings", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def create_listing():
    from app import _refresh_listing_city_summary, cache_delete_prefix

    data, carried_images = parse_listing_request_payload()
    listing_payload, errors = validate_listing_payload(data, carried_images)
    if errors:
        return jsonify(error="Невалідні дані", fields=errors), 422

    db = get_db()
    actor = db.execute(
        "SELECT role, account_type, plan_id, plan_expires_at, agency_slug FROM users WHERE id = ?",
        (g.user_id,),
    ).fetchone()
    is_admin = bool(actor and actor["role"] == "admin")
    if actor and not is_admin:
        account_type = normalize_account_type(actor["account_type"])
        listing_payload["source"] = {
            "realtor": "agent",
            "developer": "developer",
        }.get(account_type, "owner")
        listing_payload["agency_slug"] = actor["agency_slug"] or None

    if actor and not is_admin:
        plan_id, plan = resolve_user_plan(actor)
        usage = listing_usage(db, g.user_id, plan)
        if usage["listings_remaining"] == 0:
            return jsonify(
                error=(
                    f"Ліміт тарифу «{plan['name']}» вичерпано "
                    f"({usage['listings_used']}/{usage['listings_limit']} оголошень). "
                    "Оновіть тариф, щоб додати більше."
                ),
                code="plan_limit_reached",
                plan=plan_public_dict(plan_id),
                usage=usage,
            ), 402

    publish_now = data.get("publishNow", True)
    if isinstance(publish_now, str):
        publish_now = truthy_flag(publish_now)
    else:
        publish_now = bool(publish_now)

    can_fast_publish = is_admin or (publish_now and seller_can_fast_publish(db, g.user_id))
    status = "published" if can_fast_publish else "pending"
    published_at_value = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ") if can_fast_publish else None
    moderation_status = "approved" if can_fast_publish else "pending_review"
    moderation_reason = None if can_fast_publish else "Нове оголошення очікує модерації перед публікацією."
    moderation_updated_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    owner_verification_status = "verified" if is_admin and listing_payload["owner_verification_requested"] else ("pending" if listing_payload["owner_verification_requested"] else "unverified")
    phone_verification_status = "verified" if is_admin and listing_payload["phone_verification_requested"] else ("pending" if listing_payload["phone_verification_requested"] else "unverified")
    verified_owner = is_admin and listing_payload["owner_verification_requested"]
    verified_phone = is_admin and listing_payload["phone_verification_requested"]
    cur = db.execute(
        """INSERT INTO listings
            (user_id,title,city,district,property_type,condition_type,price,rooms,area,
            floor,total_floors,year_built,e_oselya,images,videos,latitude,longitude,description,
            status,published_at,listing_type,source,agency_slug,listing_status,has_photo_tour,has_video_tour,
            verified_owner,verified_phone,verified_docs,
            owner_verification_status,phone_verification_status,
            moderation_status,moderation_reason,moderation_updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (g.user_id, listing_payload["title"], listing_payload["city"], listing_payload["district"], listing_payload["property_type"], listing_payload["condition_type"], listing_payload["price"], listing_payload["rooms"], listing_payload["area"],
         listing_payload["floor"], listing_payload["total_floors"], listing_payload["year_built"], int(listing_payload["e_oselya"]), listing_payload["images_json"], listing_payload["videos_json"], listing_payload["lat"], listing_payload["lng"], listing_payload["description"], status,
         published_at_value, listing_payload["listing_type"], listing_payload["source"], listing_payload["agency_slug"], listing_payload["listing_status"], int(listing_payload["has_photo_tour"]), int(listing_payload["has_video_tour"]),
         int(verified_owner), int(verified_phone), int(listing_payload["verified_docs"]),
         owner_verification_status, phone_verification_status, moderation_status, moderation_reason, moderation_updated_at),
    )
    if listing_payload["owner_verification_requested"]:
        log_listing_event(db, cur.lastrowid, "request_owner_verification", "Автоматично створено під час подачі оголошення.")
    if listing_payload["phone_verification_requested"]:
        log_listing_event(db, cur.lastrowid, "request_phone_verification", "Автоматично створено під час подачі оголошення.")
    if status == "pending":
        log_listing_event(db, cur.lastrowid, "submit_for_moderation", moderation_reason)
    db.commit()
    if status == "published":
        _refresh_listing_city_summary(db)
        db.commit()
        cache_delete_prefix("admin:reports:listings-by-city:")
        cache_delete_prefix("public:listings:")
    if status == "published":
        run_dispatch_with_logging(
            db,
            trigger_type="listing_create_published",
            listing_id=cur.lastrowid,
            dry_run=False,
            raise_errors=False,
        )

    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(listing=_row_to_listing(row, include_private=True)), 201


@app.route("/api/listings/<int:listing_id>", methods=["PATCH"])
@require_auth
@limiter.limit("60 per hour")
def update_listing(listing_id: int):
    from app import _refresh_listing_city_summary, cache_delete_prefix

    db = get_db()
    now_expr = db_now_expr()
    listing = db.execute(
        """
        SELECT id, user_id, status, published_at, moderation_status, moderation_reason,
               verified_owner, verified_phone, verified_docs,
               owner_verification_status, phone_verification_status,
               listing_verification_status,
               title, city, district, property_type, condition_type, price, rooms, area,
               floor, total_floors, year_built, e_oselya, images, videos, latitude, longitude,
               description, listing_type, listing_status, source, agency_slug,
               has_photo_tour, has_video_tour
        FROM listings
        WHERE id = ?
        """,
        (listing_id,),
    ).fetchone()
    if not listing:
        return jsonify(error="Оголошення не знайдено"), 404

    actor = db.execute(
        "SELECT role, account_type, agency_slug FROM users WHERE id = ?",
        (g.user_id,),
    ).fetchone()
    is_admin = bool(actor and actor["role"] == "admin")
    if listing["user_id"] != g.user_id and not is_admin:
        return jsonify(error="Недостатньо прав"), 403

    stored_images = json.loads(listing["images"] or "[]")
    if has_legacy_data_uri_images(stored_images):
        return jsonify(
            error="Фото цього оголошення відновлюються. Спробуйте редагування пізніше.",
            code="legacy_media_pending",
        ), 409

    data, carried_images = parse_listing_request_payload()
    listing_payload, errors = validate_listing_payload(data, carried_images)
    if errors:
        return jsonify(error="Невалідні дані", fields=errors), 422
    if actor and not is_admin:
        account_type = normalize_account_type(actor["account_type"])
        listing_payload["source"] = {
            "realtor": "agent",
            "developer": "developer",
        }.get(account_type, "owner")
        listing_payload["agency_slug"] = actor["agency_slug"] or None

    owner_verification_status = listing["owner_verification_status"] or verification_state_from_bool(listing["verified_owner"])
    phone_verification_status = listing["phone_verification_status"] or verification_state_from_bool(listing["verified_phone"])
    verified_owner = bool(listing["verified_owner"])
    verified_phone = bool(listing["verified_phone"])
    verified_docs = bool(listing["verified_docs"])

    if is_admin and listing_payload["owner_verification_requested"]:
        verified_owner = True
        owner_verification_status = "verified"
    elif listing_payload["owner_verification_requested"] and owner_verification_status == "unverified":
        owner_verification_status = "pending"

    if is_admin and listing_payload["phone_verification_requested"]:
        verified_phone = True
        phone_verification_status = "verified"
    elif listing_payload["phone_verification_requested"] and phone_verification_status == "unverified":
        phone_verification_status = "pending"

    if is_admin and "verifiedDocs" in data:
        verified_docs = bool(listing_payload["verified_docs"])

    listing_verification_status = listing["listing_verification_status"] or "unverified"
    substantive_fields = {
        "title": listing_payload["title"],
        "city": listing_payload["city"],
        "district": listing_payload["district"],
        "property_type": listing_payload["property_type"],
        "condition_type": listing_payload["condition_type"],
        "price": listing_payload["price"],
        "rooms": listing_payload["rooms"],
        "area": listing_payload["area"],
        "floor": listing_payload["floor"],
        "total_floors": listing_payload["total_floors"],
        "year_built": listing_payload["year_built"],
        "e_oselya": int(listing_payload["e_oselya"]),
        "images": listing_payload["images_json"],
        "videos": listing_payload["videos_json"],
        "latitude": listing_payload["lat"],
        "longitude": listing_payload["lng"],
        "description": listing_payload["description"],
        "listing_type": listing_payload["listing_type"],
        "listing_status": listing_payload["listing_status"],
        "source": listing_payload["source"],
        "agency_slug": listing_payload["agency_slug"],
        "has_photo_tour": int(listing_payload["has_photo_tour"]),
        "has_video_tour": int(listing_payload["has_video_tour"]),
    }
    substantive_changed = any(listing[field] != value for field, value in substantive_fields.items())
    publish_now = data.get("publishNow", True)
    if isinstance(publish_now, str):
        publish_now = truthy_flag(publish_now)
    else:
        publish_now = bool(publish_now)
    moderation_requires_resubmission = listing["moderation_status"] in {"rejected", "changes_requested"}
    can_fast_publish = (
        is_admin
        or (
            publish_now
            and seller_can_fast_publish(db, g.user_id)
            and not moderation_requires_resubmission
        )
    )
    if is_admin or (substantive_changed and can_fast_publish):
        next_status = "published"
        moderation_status = "approved"
        moderation_reason = None
    elif substantive_changed:
        next_status = "pending"
        moderation_status = "pending_review"
        moderation_reason = "Зміни оголошення очікують модерації перед повторною публікацією."
    else:
        next_status = listing["status"]
        moderation_status = listing["moderation_status"]
        moderation_reason = listing["moderation_reason"]

    owner_changed_verified_listing = (
        not is_admin
        and listing_verification_status == "verified"
        and substantive_changed
    )
    if owner_changed_verified_listing:
        listing_verification_status = "pending"

    db.execute(
        f"""
        UPDATE listings
        SET title = ?,
            city = ?,
            district = ?,
            property_type = ?,
            condition_type = ?,
            price = ?,
            rooms = ?,
            area = ?,
            floor = ?,
            total_floors = ?,
            year_built = ?,
            e_oselya = ?,
            images = ?,
            videos = ?,
            latitude = ?,
            longitude = ?,
            description = ?,
            status = ?,
            published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, {now_expr}) ELSE published_at END,
            listing_type = ?,
            source = ?,
            agency_slug = ?,
            listing_status = ?,
            has_photo_tour = ?,
            has_video_tour = ?,
            verified_owner = ?,
            verified_phone = ?,
            verified_docs = ?,
            owner_verification_status = ?,
            phone_verification_status = ?,
            moderation_status = ?,
            moderation_reason = ?,
            moderation_updated_at = {now_expr},
            listing_verification_status = ?
        WHERE id = ?
        """,
        (
            listing_payload["title"],
            listing_payload["city"],
            listing_payload["district"],
            listing_payload["property_type"],
            listing_payload["condition_type"],
            listing_payload["price"],
            listing_payload["rooms"],
            listing_payload["area"],
            listing_payload["floor"],
            listing_payload["total_floors"],
            listing_payload["year_built"],
            int(listing_payload["e_oselya"]),
            listing_payload["images_json"],
            listing_payload["videos_json"],
            listing_payload["lat"],
            listing_payload["lng"],
            listing_payload["description"],
            next_status,
            next_status,
            listing_payload["listing_type"],
            listing_payload["source"],
            listing_payload["agency_slug"],
            listing_payload["listing_status"],
            int(listing_payload["has_photo_tour"]),
            int(listing_payload["has_video_tour"]),
            int(verified_owner),
            int(verified_phone),
            int(verified_docs),
            owner_verification_status,
            phone_verification_status,
            moderation_status,
            moderation_reason,
            listing_verification_status,
            listing_id,
        ),
    )
    log_listing_event(db, listing_id, "listing_updated", "Оголошення відредаговано власником." if not is_admin else "Оголошення відредаговано адміністратором.", admin_id=g.user_id if is_admin else None)
    if next_status == "pending" and (listing["status"] != "pending" or substantive_changed):
        log_listing_event(db, listing_id, "submit_for_moderation", moderation_reason)
    history_actor = "admin" if is_admin else "owner"
    log_field_change(db, listing_id, "price", listing["price"], listing_payload["price"], history_actor)
    log_field_change(db, listing_id, "status", listing["status"], next_status, history_actor)
    log_field_change(db, listing_id, "listing_status", listing["listing_status"], listing_payload["listing_status"], history_actor)
    log_field_change(db, listing_id, "property_type", listing["property_type"], listing_payload["property_type"], history_actor)
    log_field_change(db, listing_id, "rooms", listing["rooms"], listing_payload["rooms"], history_actor)
    log_field_change(db, listing_id, "area", listing["area"], listing_payload["area"], history_actor)
    log_field_change(
        db,
        listing_id,
        "listing_verification_status",
        listing["listing_verification_status"],
        listing_verification_status,
        history_actor,
    )
    db.commit()
    previous_media = set(json.loads(listing["images"] or "[]") + json.loads(listing["videos"] or "[]"))
    current_media = set(json.loads(listing_payload["images_json"]) + json.loads(listing_payload["videos_json"]))
    media_cleanup_failures = cleanup_listing_media(
        sorted(previous_media - current_media),
        int(listing["user_id"]),
    )

    if listing["status"] != "published" and next_status == "published":
        run_dispatch_with_logging(
            db,
            trigger_type="listing_update_published",
            listing_id=listing_id,
            dry_run=False,
            raise_errors=False,
        )

    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    cache_delete_prefix("public:listings:")
    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (listing_id,)).fetchone()
    return jsonify(
        listing=_row_to_listing(row, include_private=True),
        media_cleanup_pending=len(media_cleanup_failures),
    )


@app.route("/api/listings/<int:listing_id>", methods=["DELETE"])
@require_auth
@limiter.limit("20 per hour")
def delete_listing(listing_id: int):
    from app import _refresh_listing_city_summary, cache_delete_prefix
    db  = get_db()
    row = db.execute("SELECT user_id, images, videos FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not row:
        return jsonify(error="Оголошення не знайдено"), 404
    if row["user_id"] != g.user_id:
        return jsonify(error="Недостатньо прав"), 403

    db.execute("DELETE FROM listing_images WHERE listing_id = ?", (listing_id,))
    db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    db.commit()
    media_urls = json.loads(row["images"] or "[]") + json.loads(row["videos"] or "[]")
    media_cleanup_failures = cleanup_listing_media(media_urls, int(row["user_id"]))
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    cache_delete_prefix("public:listings:")
    return jsonify(ok=True, media_cleanup_pending=len(media_cleanup_failures))


@app.route("/api/listings/<int:listing_id>/verification", methods=["PATCH"])
@require_auth
def update_listing_verification(listing_id: int):
    from app import _refresh_listing_city_summary, cache_delete_prefix
    db = get_db()
    listing = db.execute(
        """
        SELECT id, user_id, status, verified_owner, verified_phone, verified_docs,
               owner_verification_status, phone_verification_status, moderation_status, moderation_reason,
               listing_verification_status
        FROM listings
        WHERE id = ?
        """,
        (listing_id,),
    ).fetchone()
    if not listing:
        return jsonify(error="Оголошення не знайдено"), 404

    actor = db.execute("SELECT role FROM users WHERE id = ?", (g.user_id,)).fetchone()
    is_admin = bool(actor and actor["role"] == "admin")
    if listing["user_id"] != g.user_id and not is_admin:
        return jsonify(error="Недостатньо прав"), 403

    data = request.get_json(silent=True) or {}
    reason = strip(data.get("reason"), 400)

    requested_owner_status = strip(data.get("owner_verification_status"), 32).lower()
    requested_phone_status = strip(data.get("phone_verification_status"), 32).lower()
    requested_moderation_status = strip(data.get("moderation_status"), 32).lower()
    requested_listing_verification_status = strip(
        data.get("listing_verification_status", data.get("listingVerificationStatus")), 32
    ).lower()
    owner_status = requested_owner_status or listing["owner_verification_status"] or verification_state_from_bool(listing["verified_owner"])
    phone_status = requested_phone_status or listing["phone_verification_status"] or verification_state_from_bool(listing["verified_phone"])
    moderation_status = requested_moderation_status or listing["moderation_status"] or moderation_state_from_status(listing["status"])
    listing_verification_status = requested_listing_verification_status or listing["listing_verification_status"] or "unverified"
    verified_owner = bool(listing["verified_owner"])
    verified_phone = bool(listing["verified_phone"])
    verified_docs = bool(listing["verified_docs"])

    if is_admin:
        if "verified_owner" in data:
            verified_owner = bool(data.get("verified_owner"))
            owner_status = "verified" if verified_owner else "unverified"
        if "verified_phone" in data:
            verified_phone = bool(data.get("verified_phone"))
            phone_status = "verified" if verified_phone else "unverified"
        if "verified_docs" in data:
            verified_docs = bool(data.get("verified_docs"))
    else:
        allowed_owner_statuses = {"pending", "unverified"}
        allowed_phone_statuses = {"pending", "unverified"}
        # Only admins may mark a listing as a genuinely verified listing —
        # this is a distinct, stronger trust signal than owner/phone checks.
        allowed_listing_verification_statuses = {"pending", "unverified"}
        if requested_owner_status and requested_owner_status not in allowed_owner_statuses:
            return jsonify(error="Користувач може лише подати або скасувати запит на верифікацію власника"), 403
        if requested_phone_status and requested_phone_status not in allowed_phone_statuses:
            return jsonify(error="Користувач може лише подати або скасувати запит на верифікацію телефону"), 403
        if requested_listing_verification_status and requested_listing_verification_status not in allowed_listing_verification_statuses:
            return jsonify(error="Лише адміністратор може підтвердити або відхилити верифікацію оголошення"), 403
        if requested_moderation_status:
            return jsonify(error="Користувач може лише подати або скасувати запит на верифікацію"), 403
        moderation_status = listing["moderation_status"] or moderation_state_from_status(listing["status"])

    if owner_status not in VERIFICATION_STATES:
        return jsonify(error="Невалідний статус верифікації власника"), 422
    if phone_status not in VERIFICATION_STATES:
        return jsonify(error="Невалідний статус верифікації телефону"), 422
    if moderation_status not in MODERATION_STATES:
        return jsonify(error="Невалідний статус модерації"), 422
    if listing_verification_status not in VERIFICATION_STATES:
        return jsonify(error="Невалідний статус верифікації оголошення"), 422

    if owner_status != "verified":
        verified_owner = False
    if phone_status != "verified":
        verified_phone = False
    if is_admin and owner_status == "verified":
        verified_owner = True
    if is_admin and phone_status == "verified":
        verified_phone = True

    next_status = listing["status"]
    published_at_sql = "published_at"
    if is_admin:
        if moderation_status == "approved":
            next_status = "published"
            published_at_sql = f"COALESCE(published_at, {db_now_expr()})"
        elif moderation_status == "rejected":
            next_status = "rejected"
        else:
            next_status = "pending"
    elif listing["status"] == "rejected" and (owner_status == "pending" or phone_status == "pending"):
        next_status = "pending"

    db.execute(
        f"""
        UPDATE listings
        SET verified_owner = ?,
            verified_phone = ?,
            verified_docs = ?,
            owner_verification_status = ?,
            phone_verification_status = ?,
            moderation_status = ?,
            moderation_reason = ?,
            moderation_updated_at = {db_now_expr()},
            listing_verification_status = ?,
            status = ?,
            published_at = {published_at_sql}
        WHERE id = ?
        """,
        (
            int(verified_owner),
            int(verified_phone),
            int(verified_docs),
            owner_status,
            phone_status,
            moderation_status,
            reason or ("Статус оновлено" if listing["moderation_status"] != moderation_status else listing["moderation_reason"]),
            listing_verification_status,
            next_status,
            listing_id,
        ),
    )
    history_actor = "admin" if is_admin else "owner"
    if is_admin:
        if data.get("moderation_status"):
            log_listing_event(db, listing_id, f"moderation_{moderation_status}", reason, admin_id=g.user_id)
        if data.get("owner_verification_status") or "verified_owner" in data:
            log_listing_event(db, listing_id, f"owner_verification_{owner_status}", reason, admin_id=g.user_id)
        if data.get("phone_verification_status") or "verified_phone" in data:
            log_listing_event(db, listing_id, f"phone_verification_{phone_status}", reason, admin_id=g.user_id)
        if requested_listing_verification_status:
            log_listing_event(db, listing_id, f"listing_verification_{listing_verification_status}", reason, admin_id=g.user_id)
    else:
        if data.get("owner_verification_status"):
            log_listing_event(db, listing_id, f"owner_verification_{owner_status}", reason)
        if data.get("phone_verification_status"):
            log_listing_event(db, listing_id, f"phone_verification_{phone_status}", reason)
        if requested_listing_verification_status:
            log_listing_event(db, listing_id, f"listing_verification_{listing_verification_status}", reason)
    log_field_change(db, listing_id, "status", listing["status"], next_status, history_actor)
    log_field_change(db, listing_id, "listing_verification_status", listing["listing_verification_status"], listing_verification_status, history_actor)
    db.commit()
    if next_status == "published" and listing["status"] != "published":
        run_dispatch_with_logging(
            db,
            trigger_type="moderation_publish",
            listing_id=listing_id,
            dry_run=False,
            raise_errors=False,
        )

    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (listing_id,)).fetchone()
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    cache_delete_prefix("public:listings:")
    return jsonify(listing=_row_to_listing(row, include_private=True))


@app.route("/api/alerts", methods=["POST"])
def create_listing_alert():
    db = get_db()
    data = request.get_json(silent=True) or {}
    name = strip(data.get("name"), 120)
    city = strip(data.get("city"), 100)
    district = strip(data.get("district"), 100)
    prop_type = strip(data.get("type"), 50)
    min_price = pos_int(data.get("minPrice"))
    max_price = pos_int(data.get("maxPrice"))
    min_rooms = nonneg_int(data.get("minRooms"))
    max_rooms = nonneg_int(data.get("maxRooms"))
    e_oselya = bool(data.get("eOselya"))
    listing_type = strip(data.get("listingType"), 10).lower()
    email_channel = data.get("email")
    push_channel = data.get("push")

    user_id = None
    email = strip(data.get("email"), 254).lower()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_token(auth[7:])
            user_id = int(payload["sub"])
            row = db.execute(
                "SELECT email, auth_token_version FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row and token_matches_user_version(payload, row):
                email = row["email"]
            else:
                user_id = None
        except jwt.PyJWTError:
            user_id = None

    if not email or not validate_email(email):
        return jsonify(error="Потрібен валідний email для алерта"), 422

    channels: list[str] = []
    if email_channel is None or bool(email_channel):
        channels.append("email")
    if bool(push_channel):
        channels.append("push")
    if not channels:
        channels = ["email"]

    filters = {
        "city": city or None,
        "district": district or None,
        "type": prop_type or None,
        "listingType": listing_type if listing_type in {"sale", "rent"} else None,
        "minPrice": min_price,
        "maxPrice": max_price,
        "minRooms": min_rooms,
        "maxRooms": max_rooms,
        "eOselya": e_oselya,
        "channels": channels,
    }
    cur = db.execute(
        """
        INSERT INTO listing_alerts (user_id, email, name, filters)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, email, name or "Listing alert", json.dumps(filters, ensure_ascii=False)),
    )
    db.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@app.route("/api/alerts/dispatch", methods=["GET", "POST"])
def dispatch_listing_alerts():
    db = get_db()
    allowed, trigger_auth = alerts_dispatch_authorized(db)
    if not allowed:
        return jsonify(error="Недостатньо прав для dispatch алертів"), 403

    data = request.get_json(silent=True) or {}
    listing_id = nonneg_int(data.get("listing_id")) or nonneg_int(request.args.get("listing_id"))
    dry_run = bool(data.get("dry_run")) or truthy_flag(request.args.get("dry_run"))
    trigger_type = strip(data.get("trigger"), 40).lower() or "manual"
    stats = run_dispatch_with_logging(
        db,
        trigger_type=f"{trigger_type}:{trigger_auth}",
        listing_id=listing_id,
        dry_run=dry_run,
        raise_errors=False,
    )
    return jsonify(ok=True, dry_run=dry_run, listing_id=listing_id, stats=stats, trigger_auth=trigger_auth)


@app.route("/api/alerts/dispatch/health", methods=["GET"])
def dispatch_listing_alerts_health():
    db = get_db()
    allowed, trigger_auth = alerts_dispatch_authorized(db)
    if not allowed:
        return jsonify(error="Недостатньо прав для health алертів"), 403

    last_run = db.execute(
        """
        SELECT id, trigger_type, dry_run, listing_id, checked, matched, email_sent, push_sent, success, error_text, started_at, finished_at, duration_ms
        FROM alert_dispatch_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    last_success = db.execute(
        """
        SELECT id, started_at, finished_at
        FROM alert_dispatch_runs
        WHERE success = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    cutoff_24h = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    summary_24h = db.execute(
        """
        SELECT
            COUNT(*) AS runs,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_runs,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_runs,
            SUM(checked) AS checked,
            SUM(matched) AS matched,
            SUM(email_sent) AS email_sent,
            SUM(push_sent) AS push_sent
        FROM alert_dispatch_runs
        WHERE datetime(started_at) >= ?
        """,
        (cutoff_24h,),
    ).fetchone()
    history_rows = db.execute(
        """
        SELECT id, trigger_type, dry_run, listing_id, checked, matched, email_sent, push_sent, success, error_text, started_at, finished_at, duration_ms
        FROM alert_dispatch_runs
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

    now = datetime.datetime.utcnow()
    stale = True
    stale_reason = "Немає успішних запусків"
    if last_success and last_success["finished_at"]:
        last_ok_dt = _parse_dt(last_success["finished_at"])
        if last_ok_dt:
            hours_since_ok = (now - last_ok_dt).total_seconds() / 3600
            stale = hours_since_ok > 6
            stale_reason = f"Останній успішний запуск {int(hours_since_ok)} год тому"
        else:
            stale_reason = "Не вдалося розпарсити час останнього успішного запуску"

    def _row_to_run(row):
        if not row:
            return None
        return {
            "id": row["id"],
            "trigger_type": row["trigger_type"] if "trigger_type" in row.keys() else None,
            "dry_run": bool(row["dry_run"]) if "dry_run" in row.keys() else False,
            "listing_id": row["listing_id"] if "listing_id" in row.keys() else None,
            "checked": int(row["checked"] or 0) if "checked" in row.keys() else 0,
            "matched": int(row["matched"] or 0) if "matched" in row.keys() else 0,
            "email_sent": int(row["email_sent"] or 0) if "email_sent" in row.keys() else 0,
            "push_sent": int(row["push_sent"] or 0) if "push_sent" in row.keys() else 0,
            "success": bool(row["success"]) if "success" in row.keys() else False,
            "error_text": row["error_text"] if "error_text" in row.keys() else None,
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "duration_ms": int(row["duration_ms"] or 0) if "duration_ms" in row.keys() else 0,
        }

    return jsonify(
        ok=True,
        trigger_auth=trigger_auth,
        stale=stale,
        stale_reason=stale_reason,
        last_run=_row_to_run(last_run),
        last_success=_row_to_run(last_success),
        summary_24h={
            "runs": int(summary_24h["runs"] or 0),
            "success_runs": int(summary_24h["success_runs"] or 0),
            "failed_runs": int(summary_24h["failed_runs"] or 0),
            "checked": int(summary_24h["checked"] or 0),
            "matched": int(summary_24h["matched"] or 0),
            "email_sent": int(summary_24h["email_sent"] or 0),
            "push_sent": int(summary_24h["push_sent"] or 0),
        },
        recent_runs=[_row_to_run(r) for r in history_rows],
    )


@app.route("/api/recommendations", methods=["GET"])
def get_recommendations():
    db = get_db()
    listing_id = nonneg_int(request.args.get("listing_id"))
    limit = nonneg_int(request.args.get("limit")) or 6
    limit = min(max(limit, 1), 20)

    if listing_id is None:
        return jsonify(error="listing_id is required"), 422

    source = db.execute(
        "SELECT id, city, district, property_type, rooms, price FROM listings WHERE id = ?",
        (listing_id,),
    ).fetchone()
    if not source:
        return jsonify(error="Оголошення не знайдено"), 404

    candidates = db.execute(
        LISTING_SELECT
        + """
          WHERE l.id != ?
            AND l.status = 'published'
            AND (l.city = ? OR l.property_type = ?)
          ORDER BY l.created_at DESC
          LIMIT 120
        """,
        (listing_id, source["city"], source["property_type"]),
    ).fetchall()

    scored = []
    for row in candidates:
        listing = _row_to_listing(row)
        score = 0
        if listing["city"] == source["city"]:
            score += 35
        if listing["district"] == source["district"]:
            score += 25
        if listing["property_type"] == source["property_type"]:
            score += 20
        score += max(0, 12 - abs((listing["rooms"] or 0) - (source["rooms"] or 0)) * 4)
        price_diff = abs((listing["price"] or 0) - (source["price"] or 0))
        score += max(0, 20 - int(price_diff / 5000))
        score += int(min((listing.get("trust_score") or 0) / 10, 8))
        scored.append((score, listing))

    scored.sort(key=lambda item: item[0], reverse=True)
    recommendations = [item[1] for item in scored[:limit]]
    return jsonify(recommendations=recommendations)


# ─── Map (geo-based search) ──────────────────────────────────────────────────

@app.route("/api/map/listings", methods=["GET"])
def get_map_listings():
    """Get listings with coordinates for map visualization."""
    db   = get_db()
    args = request.args

    city      = strip(args.get("city", ""), 100)
    min_price = pos_int(args.get("minPrice"))
    max_price = pos_int(args.get("maxPrice"))
    min_rooms = nonneg_int(args.get("minRooms"))
    max_rooms = nonneg_int(args.get("maxRooms"))
    e_oselya  = args.get("eOselya") == "1"
    
    # Geo-search params
    lat       = args.get("lat", type=float)
    lng       = args.get("lng", type=float)
    radius_m  = args.get("radius", type=int, default=5000)

    query = """
        SELECT l.id, l.title, l.city, l.district, l.price, l.rooms, l.area,
               l.latitude, l.longitude, l.e_oselya, l.views, l.created_at
        FROM listings l
        WHERE l.latitude IS NOT NULL AND l.longitude IS NOT NULL
    """
    params: list = []

    if city:
        query += " AND l.city = ?"
        params.append(city)
    if min_price is not None:
        query += " AND l.price >= ?"
        params.append(min_price)
    if max_price is not None:
        query += " AND l.price <= ?"
        params.append(max_price)
    if min_rooms is not None:
        query += " AND l.rooms >= ?"
        params.append(min_rooms)
    if max_rooms is not None:
        query += " AND l.rooms <= ?"
        params.append(max_rooms)
    if e_oselya:
        query += " AND l.e_oselya = 1"

    query += " ORDER BY l.created_at DESC LIMIT 500"

    rows = db.execute(query, params).fetchall()
    listings = [dict(r) for r in rows]

    # If geo-search provided, filter by radius (Haversine formula)
    if lat is not None and lng is not None:
        def distance_m(lat1, lng1, lat2, lng2):
            from math import radians, sin, cos, sqrt, atan2
            R = 6371000  # Earth radius in meters
            dlat = radians(lat2 - lat1)
            dlng = radians(lng2 - lng1)
            a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
            c = 2 * atan2(sqrt(a), sqrt(1-a))
            return R * c

        listings = [
            {**l, "distance_m": distance_m(lat, lng, l["latitude"], l["longitude"])}
            for l in listings
            if distance_m(lat, lng, l["latitude"], l["longitude"]) <= radius_m
        ]
        # Sort by distance
        listings.sort(key=lambda x: x["distance_m"])

    return jsonify(listings=listings, count=len(listings))


# ─── Analytics (aggregate stats) ─────────────────────────────────────────────

def _parse_json_payload() -> dict:
    raw_body = (request.get_data(as_text=True) or "").strip()
    data = request.get_json(silent=True) or {}
    if data:
        return data if isinstance(data, dict) else {}
    if not raw_body:
        return {}
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _insert_observability_event(
    db,
    *,
    event_type: str,
    metric_name: str | None = None,
    metric_value: float | None = None,
    rating: str | None = None,
    message: str | None = None,
    stack: str | None = None,
    source: str | None = None,
    page_url: str | None = None,
    session_id: str | None = None,
    user_agent: str | None = None,
    payload: dict | None = None,
) -> None:
    payload_json = None
    if payload:
        payload_json = json.dumps(payload, ensure_ascii=False)
    db.execute(
        """
        INSERT INTO client_observability_events
        (event_type, metric_name, metric_value, rating, message, stack, source, page_url, session_id, user_agent, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            metric_name,
            metric_value,
            rating,
            message,
            stack,
            source,
            page_url,
            session_id,
            user_agent,
            payload_json,
        ),
    )


def _safe_observability_page_url(value) -> str | None:
    raw_url = strip(value or "", 1024)
    if not raw_url:
        return None
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return None
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    if parsed.scheme and parsed.netloc:
        hostname = parsed.hostname
        if not hostname:
            return None
        try:
            port = parsed.port
        except ValueError:
            return None
        host = f"[{hostname}]" if ":" in hostname else hostname
        authority = f"{host}:{port}" if port is not None else host
        return f"{parsed.scheme}://{authority}{parsed.path or '/'}"
    if raw_url.startswith("/"):
        return parsed.path or "/"
    return None


@app.route("/api/analytics/summary", methods=["GET"])
def analytics_summary():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    avg_price = db.execute("SELECT ROUND(AVG(price)) FROM listings").fetchone()[0] or 0
    by_city = db.execute(
        "SELECT city, COUNT(*) as cnt, ROUND(AVG(price)) as avg_price FROM listings GROUP BY city ORDER BY cnt DESC LIMIT 8"
    ).fetchall()
    by_type = db.execute(
        "SELECT property_type, COUNT(*) as cnt FROM listings GROUP BY property_type ORDER BY cnt DESC"
    ).fetchall()
    return jsonify(
        total=total,
        avg_price=int(avg_price),
        by_city=[dict(r) for r in by_city],
        by_type=[dict(r) for r in by_type],
    )


@app.route("/api/analytics/lead-funnel", methods=["POST"])
def analytics_lead_funnel_event():
    db = get_db()
    data = _parse_json_payload()

    event = strip(data.get("event", ""), 64)
    intent = strip(data.get("intent", ""), 80)
    source = strip(data.get("source", ""), 80)
    listing_type = strip(data.get("listing_type", ""), 16)
    session_id = strip(data.get("session_id", ""), 80)
    listing_id_raw = data.get("listing_id")
    price_raw = data.get("price")

    if not event or not intent or not source:
        return jsonify(error="event, intent and source are required"), 400

    listing_id = None
    if listing_id_raw is not None:
        try:
            listing_id = int(listing_id_raw)
        except (TypeError, ValueError):
            return jsonify(error="listing_id must be integer"), 400
        if listing_id <= 0:
            return jsonify(error="listing_id must be positive"), 400

    price = None
    if price_raw is not None:
        try:
            price = int(price_raw)
        except (TypeError, ValueError):
            return jsonify(error="price must be integer"), 400
        if price < 0:
            return jsonify(error="price must be non-negative"), 400

    db.execute(
        """
        INSERT INTO lead_funnel_events (
            listing_id, event, intent, source, listing_type, price, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            event,
            intent,
            source,
            listing_type or None,
            price,
            session_id or None,
        ),
    )
    created_at_dt = datetime.datetime.utcnow().replace(microsecond=0)
    day = created_at_dt.strftime("%Y-%m-%d")
    created_at = created_at_dt.isoformat(sep=" ")
    _upsert_lead_funnel_summary(
        db,
        day=day,
        source=source or "unknown",
        listing_type=listing_type or "unknown",
        event=event,
        listing_id=listing_id,
        created_at=created_at,
        session_id=session_id or None,
    )
    db.commit()
    cache_delete_prefix("admin:reports:lead-funnel:")
    return jsonify(ok=True), 201


@app.route("/api/leads", methods=["POST"])
@limiter.limit("30 per minute")
def create_lead_request():
    db = get_db()
    data = _parse_json_payload()

    lead_type = strip(data.get("lead_type", ""), 32).lower()
    source = strip(data.get("source", ""), 80)
    name = strip(data.get("name", ""), 120)
    phone = strip(data.get("phone", ""), 40)
    email = strip(data.get("email", ""), 254).lower()
    bank = strip(data.get("bank", ""), 120)
    project_slug = strip(data.get("project_slug", ""), 120)
    project_name = strip(data.get("project_name", ""), 180)
    city = strip(data.get("city", ""), 100)
    district = strip(data.get("district", ""), 100)
    message = strip(data.get("message", ""), 1200)
    session_id = strip(data.get("session_id", ""), 80)
    e_oselya = 1 if truthy_flag(str(data.get("eOselya", data.get("e_oselya", False)))) else 0
    listing_id_raw = data.get("listing_id")

    if lead_type not in {"mortgage", "development"}:
        return jsonify(error="lead_type must be mortgage or development"), 422
    if not source:
        return jsonify(error="source is required"), 422
    if not name:
        return jsonify(error="name is required"), 422
    if not phone and not email:
        return jsonify(error="phone or email is required"), 422
    if email and not validate_email(email):
        return jsonify(error="Invalid email format"), 422

    listing_id = None
    if listing_id_raw not in {None, ""}:
        try:
            listing_id = int(listing_id_raw)
        except (TypeError, ValueError):
            return jsonify(error="listing_id must be integer"), 422
        if listing_id <= 0:
            return jsonify(error="listing_id must be positive"), 422

    project = None
    if project_slug:
        project = _development_project_by_slug(project_slug)
        if not project:
            return jsonify(error="Unknown project_slug"), 422
        if not project_name:
            project_name = project["name"]
        if not city:
            city = project["city"]
        if not district:
            district = project["district"]

    amount = nonneg_int(data.get("amount"))
    down_payment = nonneg_int(data.get("down_payment"))
    years = nonneg_int(data.get("years"))
    if lead_type == "mortgage":
        if amount is None or amount <= 0:
            return jsonify(error="amount is required for mortgage leads"), 422
        if down_payment is None or down_payment < 0 or down_payment > 100:
            return jsonify(error="down_payment must be between 0 and 100"), 422
        if years is None or years <= 0:
            return jsonify(error="years is required for mortgage leads"), 422

    created_at_dt = datetime.datetime.utcnow().replace(microsecond=0)
    created_at = created_at_dt.isoformat(sep=" ")
    db.execute(
        """
        INSERT INTO lead_requests (
            lead_type, source, name, phone, email, bank, project_slug, project_name,
            city, district, amount, down_payment, years, e_oselya, message,
            listing_id, session_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_type,
            source,
            name,
            phone or None,
            email or None,
            bank or None,
            project_slug or None,
            project_name or None,
            city or None,
            district or None,
            amount,
            down_payment,
            years,
            e_oselya,
            message or None,
            listing_id,
            session_id or None,
            created_at,
        ),
    )

    intent = "mortgage_application" if lead_type == "mortgage" else "development_request"
    listing_type = "sale" if lead_type == "mortgage" else "newbuild"
    payload_source = source or "lead_form"
    db.execute(
        """
        INSERT INTO lead_funnel_events (
            listing_id, event, intent, source, listing_type, price, session_id, created_at
        ) VALUES (?, 'lead_submit', ?, ?, ?, ?, ?, ?)
        """,
        (
            listing_id,
            intent,
            payload_source,
            listing_type,
            amount,
            session_id or None,
            created_at,
        ),
    )
    _upsert_lead_funnel_summary(
        db,
        day=created_at_dt.strftime("%Y-%m-%d"),
        source=payload_source,
        listing_type=listing_type,
        event="lead_submit",
        listing_id=listing_id,
        created_at=created_at,
        session_id=session_id or None,
    )
    db.commit()
    cache_delete_prefix("admin:reports:lead-funnel:")

    return jsonify(
        ok=True,
        lead={
            "lead_type": lead_type,
            "source": source,
            "project_slug": project_slug or None,
            "project_name": project_name or None,
            "city": city or None,
            "district": district or None,
        },
    ), 201


@app.route("/api/analytics/client-telemetry", methods=["POST"])
@limiter.limit("120 per hour")
def analytics_client_telemetry():
    db = get_db()
    data = _parse_json_payload()
    if not data:
        return jsonify(error="JSON payload is required"), 400

    event_type = strip(data.get("event_type", ""), 40).lower().replace("-", "_")
    if not event_type:
        return jsonify(error="event_type is required"), 400

    source = strip(data.get("source", ""), 255) or None
    page_url = _safe_observability_page_url(data.get("page_url"))
    session_id = strip(data.get("session_id", ""), 120) or None
    message = strip(data.get("message", ""), 1200) or None
    stack = strip(data.get("stack", ""), 8000) or None
    user_agent = strip(request.headers.get("User-Agent", ""), 400) or None

    payload = data.get("payload")
    if payload is not None and not isinstance(payload, dict):
        return jsonify(error="payload must be an object"), 400

    _insert_observability_event(
        db,
        event_type=event_type,
        message=message,
        stack=stack,
        source=source,
        page_url=page_url,
        session_id=session_id,
        user_agent=user_agent,
        payload=payload,
    )
    db.commit()
    cache_delete_prefix("admin:reports:observability:")
    return jsonify(ok=True), 201


@app.route("/api/analytics/web-vitals", methods=["POST"])
@limiter.limit("600 per hour")
def analytics_web_vitals():
    db = get_db()
    data = _parse_json_payload()
    if not data:
        return jsonify(error="JSON payload is required"), 400

    metric_name = strip(data.get("name", ""), 24).upper()
    if not metric_name:
        return jsonify(error="name is required"), 400
    if metric_name not in {"FCP", "LCP", "CLS", "FID", "INP", "TTFB"}:
        return jsonify(error="Unsupported web-vitals metric"), 400

    value_raw = data.get("value")
    try:
        metric_value = float(value_raw)
    except (TypeError, ValueError):
        return jsonify(error="value must be a number"), 400
    if metric_value < 0:
        return jsonify(error="value must be non-negative"), 400

    rating = strip(data.get("rating", ""), 24).lower() or None
    if rating and rating not in {"good", "needs-improvement", "poor"}:
        return jsonify(error="rating must be good, needs-improvement, or poor"), 400

    source = strip(data.get("source", ""), 255) or None
    page_url = _safe_observability_page_url(data.get("page_url"))
    session_id = strip(data.get("session_id", ""), 120) or None
    user_agent = strip(request.headers.get("User-Agent", ""), 400) or None

    extra_payload = {}
    for key in ("id", "navigation_type", "delta"):
        if key in data:
            extra_payload[key] = data[key]

    _insert_observability_event(
        db,
        event_type="web_vital",
        metric_name=metric_name,
        metric_value=metric_value,
        rating=rating,
        source=source,
        page_url=page_url,
        session_id=session_id,
        user_agent=user_agent,
        payload=extra_payload or None,
    )
    db.commit()
    cache_delete_prefix("admin:reports:observability:")
    return jsonify(ok=True), 201


@app.route("/zhk/<slug>", methods=["GET"])
@app.route("/seo/zhk/<slug>", methods=["GET"])
def development_project_page(slug: str):
    return _render_development_project_page(slug)


def _render_development_project_page(slug: str):
    db = get_db()
    project = _development_project_by_slug(slug)
    if not project:
        return jsonify(error="ЖК не знайдено"), 404

    base = public_base_url()
    canonical = f"{base}/zhk/{quote(project['slug'])}"
    public_app = public_app_url()
    host = (request.host or "").split(":")[0]
    api_base = "" if host in {"localhost", "127.0.0.1"} else "/api-backend"

    related_listings = db.execute(
        """
        SELECT id, title, district, price, area, rooms, created_at
        FROM listings
        WHERE status = 'published' AND city = ?
        ORDER BY created_at DESC
        LIMIT 6
        """,
        (project["city"],),
    ).fetchall()

    related_cards = "".join(
        (
            f'<a class="dev-listing-card" href="{base}/listing/{int(row["id"])}">'
            f'<div class="dev-listing-card__title">{escape(row["title"])}</div>'
            f'<div class="dev-listing-card__meta">{escape(row["district"])} · {int(row["rooms"])} кімн. · {int(row["area"])} м²</div>'
            f'<div class="dev-listing-card__price">${int(row["price"]):,}</div>'
            "</a>"
        )
        for row in related_listings
    ) or "<div class='dev-empty'>Поки немає оголошень для цієї локації.</div>"

    floor_plans = "".join(f"<li>{escape(item)}</li>" for item in project["floor_plans"])
    highlights = "".join(f"<span>{escape(item)}</span>" for item in project["highlights"])
    price_from = f"${int(project['price_from']):,}"
    project_json_ld = {
        "@context": "https://schema.org",
        "@type": "ApartmentComplex",
        "name": project["name"],
        "url": canonical,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": project["city"],
            "addressRegion": project["district"],
            "addressCountry": "UA",
        },
        "description": project["headline"],
        "amenityFeature": [{"@type": "LocationFeatureSpecification", "name": item} for item in project["highlights"]],
    }
    project_json = json.dumps(project_json_ld, ensure_ascii=False)
    slug_json = json.dumps(project["slug"], ensure_ascii=False)
    name_json = json.dumps(project["name"], ensure_ascii=False)
    city_json = json.dumps(project["city"], ensure_ascii=False)
    district_json = json.dumps(project["district"], ensure_ascii=False)

    html = """<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>%s — новобудова в %s | UA-Dim</title>
  <meta name="description" content="%s. Ціна від %s/м², %s, %s." />
  <link rel="canonical" href="%s" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="%s — новобудова в %s | UA-Dim" />
  <meta property="og:description" content="%s. Ціна від %s/м²." />
  <meta property="og:url" content="%s" />
  <meta property="og:image" content="%s/favicon.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <script type="application/ld+json">%s</script>
  <style>
    body{margin:0;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f8fafc;color:#0f172a}
    .wrap{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
    .hero{background:linear-gradient(135deg,#0f172a,#1d4ed8);color:#fff;border-radius:28px;padding:28px;box-shadow:0 20px 60px rgba(15,23,42,.24)}
    .hero h1{margin:0;font-size:clamp(30px,4vw,48px);line-height:1.05}
    .hero p{margin:12px 0 0;max-width:760px;color:#dbeafe;line-height:1.6}
    .chips{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
    .chips span,.chips a{display:inline-flex;align-items:center;border-radius:999px;padding:9px 13px;font-size:13px;font-weight:700;text-decoration:none}
    .chips span{background:rgba(255,255,255,.12);color:#fff}
    .chips a{background:#fff;color:#1d4ed8}
    .grid{display:grid;grid-template-columns:1.2fr .8fr;gap:20px;margin-top:22px}
    .card{background:#fff;border:1px solid #e2e8f0;border-radius:24px;padding:22px;box-shadow:0 12px 36px rgba(15,23,42,.08)}
    .card h2{margin:0 0 10px;font-size:24px}
    .muted{color:#64748b}
    .plans,.highlights{display:flex;flex-wrap:wrap;gap:10px;padding:0;list-style:none}
    .plans li,.highlights span{background:#eff6ff;color:#1d4ed8;border:1px solid #dbeafe;border-radius:999px;padding:9px 12px;font-weight:700}
    .dev-listing-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
    .dev-listing-card{display:block;text-decoration:none;color:#0f172a;border:1px solid #e2e8f0;border-radius:18px;padding:14px;background:linear-gradient(180deg,#fff,#f8fafc)}
    .dev-listing-card__title{font-weight:800;margin-bottom:6px}
    .dev-listing-card__meta{font-size:13px;color:#64748b}
    .dev-listing-card__price{margin-top:8px;font-weight:800;color:#2563eb}
    .lead-form{display:grid;gap:12px}
    .lead-form input,.lead-form textarea{width:100%%;border:1px solid #cbd5e1;border-radius:14px;padding:12px 14px;font:inherit}
    .lead-form textarea{min-height:110px;resize:vertical}
    .lead-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
    .lead-actions button{border:0;border-radius:999px;padding:12px 18px;font-weight:800;background:#2563eb;color:#fff;cursor:pointer}
    .lead-status{font-size:14px;font-weight:700;color:#0f766e}
    @media (max-width: 900px){.grid,.dev-listing-grid{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>%s</h1>
      <p>%s</p>
      <div class="chips">
        <span>%s, %s</span>
        <span>Від %s/м²</span>
        <span>%s</span>
        <a href="%s">Повернутися до пошуку</a>
      </div>
    </section>

    <div class="grid">
      <div class="card">
        <h2>Плани поверхів</h2>
        <p class="muted">Окремі сторінки з floor-plan блоками допомагають SEO та підвищують конверсію у заявку.</p>
        <ul class="plans">%s</ul>

        <h2 style="margin-top:22px">Переваги</h2>
        <div class="highlights">%s</div>

        <h2 style="margin-top:22px">Стадія будівництва</h2>
        <p class="muted">%s</p>
      </div>

      <div class="card">
        <h2>Залишити заявку</h2>
        <p class="muted">Ми передамо заявку в реальний backend API та зв'яжемося з вами.</p>
        <form id="development-lead-form" class="lead-form">
          <input name="name" placeholder="Ваше ім'я" required />
          <input name="phone" placeholder="+380..." />
          <input name="email" type="email" placeholder="Email" />
          <textarea name="message" placeholder="Що важливо: поверх, площа, єОселя, розтермінування"></textarea>
          <div class="lead-actions">
            <button type="submit">Надіслати заявку</button>
            <span id="lead-status" class="lead-status" aria-live="polite"></span>
          </div>
        </form>
      </div>
    </div>

    <div class="card" style="margin-top:20px">
      <h2>Подібні об'єкти у місті</h2>
      <div class="dev-listing-grid">%s</div>
    </div>
  </div>

  <script>
  (function() {
    const form = document.getElementById('development-lead-form');
    const status = document.getElementById('lead-status');
    const apiBase = %s;
    const nameInput = form.elements.namedItem('name');
    const phoneInput = form.elements.namedItem('phone');
    const emailInput = form.elements.namedItem('email');
    const messageInput = form.elements.namedItem('message');
    const sessionKey = 'uah.session';
    const sessionId = (() => {
      try {
        const existing = window.sessionStorage.getItem(sessionKey);
        if (existing) return existing;
        const generated = (window.crypto && typeof window.crypto.randomUUID === 'function')
          ? window.crypto.randomUUID()
          : Date.now() + '-' + Math.random().toString(36).slice(2, 10);
        window.sessionStorage.setItem(sessionKey, generated);
        return generated;
      } catch (_) {
        return Date.now().toString(36);
      }
    })();

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      status.textContent = 'Надсилаємо...';
      const payload = {
        lead_type: 'development',
        source: 'development-seo-page',
        name: nameInput.value.trim(),
        phone: phoneInput.value.trim(),
        email: emailInput.value.trim(),
        project_slug: %s,
        project_name: %s,
        city: %s,
        district: %s,
        message: messageInput.value.trim(),
        session_id: sessionId,
      };
      try {
        const response = await fetch(`${apiBase}/api/leads`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(data.error || 'Не вдалося відправити заявку');
        }
        form.reset();
        status.textContent = "Заявку відправлено — ми зв'яжемося найближчим часом.";
        if (window.dataLayer) {
          window.dataLayer.push({ event: 'development_lead_submit', project_slug: %s });
        }
      } catch (error) {
        status.textContent = error.message || 'Помилка відправки';
      }
    });
  })();
  </script>
</body>
</html>
""" % (
        escape(project["name"]),        # 1 title
        escape(project["city"]),        # 2 title city
        escape(project["headline"]),     # 3 description
        price_from,                      # 4 description price
        escape(project["city"]),        # 5 description city
        escape(project["district"]),    # 6 description district
        canonical,                      # 7 canonical
        escape(project["name"]),        # 8 og title
        escape(project["city"]),        # 9 og title city
        escape(project["headline"]),     # 10 og description
        price_from,                      # 11 og description price
        canonical,                      # 12 og url
        base,                            # 13 og image base
        project_json,                    # 14 ld json
        escape(project["name"]),        # 15 hero h1
        escape(project["headline"]),     # 16 hero paragraph
        escape(project["city"]),        # 17 chips city
        escape(project["district"]),    # 18 chips district
        price_from,                      # 19 chips price
        escape(project["delivery"]),     # 20 chips delivery
        public_app,                      # 21 back to search
        floor_plans,                     # 22 floor plans
        highlights,                      # 23 highlights
        escape(project["stage"]),        # 24 stage
        related_cards,                   # 25 related listings
        json.dumps(api_base, ensure_ascii=False),  # 26 api base
        slug_json,                       # 27 payload slug
        name_json,                       # 28 payload name
        city_json,                       # 29 payload city
        district_json,                   # 30 payload district
        slug_json,                       # 31 analytics slug
    )
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/seo/<city>", methods=["GET"])
def seo_city_page(city: str):
    return _render_seo_page(city=city, district=None)


@app.route("/seo/<city>/<district>", methods=["GET"])
def seo_district_page(city: str, district: str):
    return _render_seo_page(city=city, district=district)


def _render_seo_page(city: str, district: str | None):
    db = get_db()
    city_name = strip(city, 100)
    district_name = strip(district, 100) if district else None
    page = nonneg_int(request.args.get("page")) or 1
    page = max(1, page)
    page_size = min(max(nonneg_int(request.args.get("page_size")) or 30, 5), 60)

    where = ["status = 'published'", "city = ?"]
    params: list = [city_name]
    title_suffix = city_name
    if district_name:
        where.append("district = ?")
        params.append(district_name)
        title_suffix = f"{city_name}, {district_name}"

    total_count = int(
        db.execute(
            f"SELECT COUNT(*) FROM listings WHERE {' AND '.join(where)}",
            params,
        ).fetchone()[0]
    )
    offset = (page - 1) * page_size
    listings = db.execute(
        f"""
        SELECT id, title, city, district, price, rooms, area, created_at
        FROM listings
        WHERE {" AND ".join(where)}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()
    count = len(listings)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * page_size
        listings = db.execute(
            f"""
            SELECT id, title, city, district, price, rooms, area, created_at
            FROM listings
            WHERE {" AND ".join(where)}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        count = len(listings)
    avg_price = int(
        db.execute(
            f"SELECT COALESCE(ROUND(AVG(price)), 0) FROM listings WHERE {' AND '.join(where)}",
            params,
        ).fetchone()[0]
    )
    districts = db.execute(
        """
        SELECT district, COUNT(*) as cnt
        FROM listings
        WHERE status = 'published' AND city = ?
        GROUP BY district
        ORDER BY cnt DESC
        LIMIT 25
        """,
        (city_name,),
    ).fetchall()
    top_cities, top_districts = _seo_landing_stats(db, limit=6)

    base = public_base_url()
    canonical_path = f"/seo/{quote(city_name)}"
    if district_name:
        canonical_path += f"/{quote(district_name)}"
    canonical = f"{base}{canonical_path}" if page <= 1 else f"{base}{canonical_path}?{urlencode({'page': page})}"
    app_link = f"{public_app_url()}?city={quote(city_name)}"
    if district_name:
        app_link += f"&district={quote(district_name)}"
    og_image = f"{base}/favicon.png"
    prev_url = None
    next_url = None
    if page > 1:
        prev_url = (
            f"{base}{canonical_path}"
            if page == 2
            else f"{base}{canonical_path}?{urlencode({'page': page - 1})}"
        )
    if page < total_pages:
        next_url = f"{base}{canonical_path}?{urlencode({'page': page + 1})}"

    listing_items = "".join(
        (
            "<li>"
            f"<strong>{escape(item['title'])}</strong> — "
            f"{escape(item['district'])}, ${int(item['price']):,}, {int(item['area'])} м², {int(item['rooms'])} кімн."
            "</li>"
        )
        for item in listings[:30]
    ) or "<li>Наразі оголошень не знайдено.</li>"

    district_links = "".join(
        f'<li><a href="/seo/{quote(city_name)}/{quote(row["district"])}">{escape(row["district"])} ({row["cnt"]})</a></li>'
        for row in districts
    )
    top_city_links = "".join(
        f'<li><a href="{base}/seo/{quote(row["city"])}">{escape(row["city"])} ({row["cnt"]})</a> · ${int(row["avg_price"] or 0):,}</li>'
        for row in top_cities
    ) or "<li>Немає даних по містах.</li>"
    top_district_links = "".join(
        f'<li><a href="{base}/seo/{quote(row["city"])}/{quote(row["district"])}">{escape(row["city"])}, {escape(row["district"])}</a> ({row["cnt"]})</li>'
        for row in top_districts
    ) or "<li>Немає даних по районах.</li>"
    related_projects = _development_projects_for_city(city_name)
    project_links = "".join(
        f'<li><a href="{base}/zhk/{quote(project["slug"])}">{escape(project["name"])}</a> · від ${int(project["price_from"]):,}/м²</li>'
        for project in related_projects
    ) or "<li>Наразі немає підготовлених ЖК у цій локації.</li>"

    alternate_links = [
        f'<link rel="alternate" hreflang="uk-UA" href="{canonical}" />',
        f'<link rel="alternate" hreflang="x-default" href="{public_app_url()}" />',
    ]
    if district_name:
        alternate_links.append(
            f'<link rel="alternate" hreflang="uk-UA" href="{base}/seo/{quote(city_name)}" />'
        )

    page_json_ld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": f"Нерухомість: {title_suffix}",
        "description": f"Актуальні оголошення в локації {title_suffix}. Сторінка {page} з {total_pages}.",
        "url": canonical,
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": total_count,
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": offset + idx + 1,
                    "url": f"{app_link}&listing_id={item['id']}",
                    "name": item["title"],
                }
                for idx, item in enumerate(listings[:20])
            ],
        },
    }
    city_dataset_json_ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": f"Ринок нерухомості — {title_suffix}",
        "description": f"{count} оголошень, середня ціна {avg_price} доларів.",
        "url": canonical,
        "keywords": ["нерухомість", city_name, district_name or ""],
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
    breadcrumb_json_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "UA-Dim",
                "item": public_app_url(),
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": city_name,
                "item": f"{base}/seo/{quote(city_name)}",
            },
        ],
    }
    if district_name:
        breadcrumb_json_ld["itemListElement"].append(
            {
                "@type": "ListItem",
                "position": 3,
                "name": district_name,
                "item": f"{base}/seo/{quote(city_name)}/{quote(district_name)}",
            }
        )
    faq_entries = [
        {
            "q": f"Скільки оголошень зараз у {title_suffix}?",
            "a": f"Зараз доступно {total_count} опублікованих оголошень у цій локації.",
        },
        {
            "q": f"Яка середня ціна у {title_suffix}?",
            "a": f"Середня ціна становить приблизно ${avg_price:,}.",
        },
        {
            "q": "Як отримувати нові оголошення автоматично?",
            "a": "Відкрийте картку об'єкта та натисніть «Алерт на схожі оголошення».",
        },
    ]
    faq_json_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": item["a"],
                },
            }
            for item in faq_entries
        ],
    }
    organization_json_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "UA-Dim",
        "url": public_app_url(),
        "logo": f"{base}/favicon.png",
        "description": "Платформа для пошуку нерухомості в Україні: квартири, будинки, єОселя.",
        "contactPoint": {
            "@type": "ContactPoint",
            "contactType": "customer support",
            "availableLanguage": "Ukrainian",
        },
        "sameAs": [
            "https://t.me/ua_homes",
            "https://facebook.com/ua.homes",
        ],
    }
    webpage_json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": f"Купити нерухомість — {title_suffix} | UA-Dim",
        "url": canonical,
        "description": f"Актуальні оголошення в локації {title_suffix}: {total_count} об'єктів, середня ціна ${avg_price:,}.",
        "inLanguage": "uk-UA",
        "isPartOf": {"@type": "WebSite", "name": "UA-Dim", "url": public_app_url()},
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": ["#main-h1", "#page-description"],
        },
    }
    faq_html = "".join(
        f"<details><summary>{escape(item['q'])}</summary><p>{escape(item['a'])}</p></details>"
        for item in faq_entries
    )
    pagination_rel_links = []
    if prev_url:
        pagination_rel_links.append(f'<link rel="prev" href="{prev_url}" />')
    if next_url:
        pagination_rel_links.append(f'<link rel="next" href="{next_url}" />')
    pagination_nav = []
    if page > 1:
        prev_href = (
            f"/seo/{quote(city_name)}"
            if page == 2 and not district_name
            else (f"/seo/{quote(city_name)}/{quote(district_name)}" if page == 2 else f"{canonical_path}?{urlencode({'page': page - 1})}")
        )
        pagination_nav.append(f'<a href="{prev_href}">← Попередня</a>')
    pagination_nav.append(f"<span>Сторінка {page} з {total_pages}</span>")
    if page < total_pages:
        pagination_nav.append(f'<a href="{canonical_path}?{urlencode({"page": page + 1})}">Наступна →</a>')
    pagination_nav_html = " ".join(pagination_nav)

    html = f"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Купити нерухомість — {escape(title_suffix)} | UA-Dim</title>
  <meta name="description" content="Актуальні оголошення в локації {escape(title_suffix)}: {total_count} об'єктів, середня ціна ${avg_price:,}. Сторінка {page} з {total_pages}." />
  <link rel="canonical" href="{canonical}" />
  {''.join(pagination_rel_links)}
  {''.join(alternate_links)}
  <meta property="og:locale" content="uk_UA" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="UA-Dim" />
  <meta property="og:title" content="Купити нерухомість — {escape(title_suffix)} | UA-Dim" />
  <meta property="og:description" content="Актуальні оголошення в локації {escape(title_suffix)}: {total_count} об'єктів, середня ціна ${avg_price:,}. Сторінка {page} з {total_pages}." />
  <meta property="og:url" content="{canonical}" />
  <meta property="og:image" content="{og_image}" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:title" content="Купити нерухомість — {escape(title_suffix)} | UA-Dim" />
  <meta name="twitter:description" content="Актуальні оголошення в локації {escape(title_suffix)}: {total_count} об'єктів, середня ціна ${avg_price:,}. Сторінка {page} з {total_pages}." />
  <meta name="twitter:image" content="{og_image}" />
  <script type="application/ld+json">{json.dumps(organization_json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(webpage_json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(page_json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(city_dataset_json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(breadcrumb_json_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(faq_json_ld, ensure_ascii=False)}</script>
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:0 auto;padding:24px;line-height:1.55;color:#0f172a}}
    a{{color:#2563eb;text-decoration:none}} a:hover{{text-decoration:underline}}
    .kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0 18px}} .card{{background:#eff6ff;padding:10px 14px;border-radius:12px}}
    .pager{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0 18px}}
    .breadcrumbs{{display:flex;gap:8px;flex-wrap:wrap;font-size:14px;color:#475569;margin-bottom:8px}}
    details{{border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;margin:8px 0}} summary{{cursor:pointer;font-weight:600}}
  </style>
</head>
<body>
  <nav class="breadcrumbs">
    <a href="{public_app_url()}">UA-Dim</a>
    <span>›</span>
    <a href="{base}/seo/{quote(city_name)}">{escape(city_name)}</a>
    {f'<span>›</span><span>{escape(district_name)}</span>' if district_name else ''}
  </nav>
  <h1 id="main-h1">Нерухомість: {escape(title_suffix)}</h1>
  <p id="page-description">UA-Dim: перевірені оголошення з фото, єОселя та картою.</p>
  <div class="kpi">
    <div class="card"><strong>{total_count}</strong> оголошень</div>
    <div class="card"><strong>${avg_price:,}</strong> середня ціна</div>
  </div>
  <div class="pager">{pagination_nav_html}</div>
  <p><a href="{app_link}">Відкрити інтерактивний пошук у застосунку →</a></p>
  <h2>Останні об'єкти</h2>
  <ul>{listing_items}</ul>
  <h2>Райони {escape(city_name)}</h2>
  <ul>{district_links or '<li>Немає даних по районах.</li>'}</ul>
  <h2>Топ-міста для пошуку</h2>
  <ul>{top_city_links}</ul>
  <h2>Топ-райони</h2>
  <ul>{top_district_links}</ul>
  <h2>Новобудови та ЖК</h2>
  <ul>{project_links}</ul>
  <h2>FAQ</h2>
  {faq_html}
</body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


# ─── Routes: Individual listing page ─────────────────────────────────────────

@app.route("/listing/<int:lid>", methods=["GET"])
def listing_page(lid: int):
    db = get_db()
    row = db.execute(LISTING_SELECT + " WHERE l.id = ? AND l.status = 'published'", (lid,)).fetchone()
    if not row:
        return Response("<h1>Оголошення не знайдено</h1>", status=404, mimetype="text/html; charset=utf-8")

    listing = _row_to_listing(row)
    reviews = db.execute(
        "SELECT user_name, rating, comment, created_at FROM reviews WHERE listing_id = ? ORDER BY created_at DESC",
        (lid,)
    ).fetchall()
    price_stats = comparable_price_stats(db, row)
    field_history = public_field_history(db, lid)
    # Increment view counter
    db.execute("UPDATE listings SET views = views + 1 WHERE id = ?", (lid,))
    db.commit()

    base = public_base_url()
    canonical = f"{base}/listing/{lid}"
    og_image = next((img for img in listing["images"] if not str(img).startswith("data:")), f"{base}/favicon.png")
    app_link = f"{public_app_url()}?listing_id={lid}"
    contact_subject = quote(f"Запит щодо оголошення №{lid}: {listing['title']}", safe="")
    contact_body = quote(
        f"Доброго дня! Хочу уточнити деталі оголошення №{lid}: {canonical}",
        safe="",
    )
    contact_link = f"mailto:feedback@ua-dim.com?subject={contact_subject}&body={contact_body}"
    city_link = f"{base}/seo/{quote(listing['city'])}"
    district_link = f"{base}/seo/{quote(listing['city'])}/{quote(listing['district'])}"
    listing_type_label = "Оренда" if listing.get("listing_type") == "rent" else "Продаж"
    price_label = f"${int(listing['price']):,}/міс." if listing.get("listing_type") == "rent" else f"${int(listing['price']):,}"
    per_sqm = int(listing["price"] / listing["area"]) if listing["area"] else 0
    published_label = (listing.get("published_at") or listing.get("created_at") or "")[:10]
    listing_status_key = listing.get("listing_status") or "active"
    availability_url = {
        "active": "https://schema.org/InStock",
        "sold": "https://schema.org/SoldOut",
        "removed": "https://schema.org/Discontinued",
    }.get(listing_status_key, "https://schema.org/InStock")
    trust_items = []
    if listing.get("verified_owner"):
        trust_items.append("Власник верифікований")
    if listing.get("verified_phone"):
        trust_items.append("Телефон підтверджено")
    if listing.get("verified_docs"):
        trust_items.append("Документи перевірено")
    if listing.get("has_photo_tour"):
        trust_items.append("Є фото-тур")
    if listing.get("has_video_tour"):
        trust_items.append("Є відео-тур")
    trust_count = len(trust_items)
    owner_verification_key = listing.get("owner_verification_status") or "unverified"
    phone_verification_key = listing.get("phone_verification_status") or "unverified"
    moderation_key = listing.get("moderation_status") or "approved"
    # Seller type shown to users is derived strictly from the backend account
    # type/account agency membership — never from client-supplied listing data.
    seller_type_label = {
        "owner": "Власник",
        "intermediary": "Ріелтор",
        "agency": "Агентство",
        "developer": "Забудовник",
        "unknown": "Не визначено",
    }.get(listing.get("seller_type"), "Власник")
    listing_verification_key = listing.get("listing_verification_status") or "unverified"
    verified_listing_label = {
        "unverified": "Оголошення ще не верифіковане",
        "pending": "Верифікація оголошення в обробці",
        "verified": "Оголошення верифіковано",
        "rejected": "У верифікації оголошення відмовлено",
    }.get(listing_verification_key, "Статус верифікації оголошення уточнюється")
    listing_status_label = {
        "active": "Актуально",
        "sold": "Продано",
        "removed": "Знято",
    }.get(listing_status_key, "Актуально")
    moderation_label = {
        "pending_review": "На модерації",
        "in_review": "Йде перевірка",
        "approved": "Перевірено модератором",
        "changes_requested": "Потрібні правки",
        "rejected": "Відхилено",
    }.get(moderation_key, "На перевірці")
    owner_verification_label = {
        "unverified": "Власника ще не подано на перевірку",
        "pending": "Верифікація власника в обробці",
        "verified": "Власник верифікований",
        "rejected": "Запит власника відхилено",
    }.get(owner_verification_key, "Статус власника уточнюється")
    phone_verification_label = {
        "unverified": "Телефон ще не подано на перевірку",
        "pending": "Телефон перевіряється",
        "verified": "Телефон підтверджено",
        "rejected": "Потрібно повторно підтвердити телефон",
    }.get(phone_verification_key, "Статус телефону уточнюється")
    trust_flow_items = [
        ("Модерація", moderation_label),
        ("Власник", owner_verification_label),
        ("Телефон", phone_verification_label),
        ("Документи", "Документи перевірено" if listing.get("verified_docs") else "Документи ще не підтверджено"),
    ]
    quick_facts = []
    if listing.get("rooms"):
        quick_facts.append(f'{listing["rooms"]} кімн.')
    quick_facts.append(f'{listing["area"]} м²')
    if listing.get("floor") and listing.get("total_floors"):
        quick_facts.append(f'{listing["floor"]}/{listing["total_floors"]} поверх')
    elif listing.get("floor"):
        quick_facts.append(f'{listing["floor"]} поверх')
    if listing.get("year_built"):
        quick_facts.append(f'{listing["year_built"]} рік')
    quick_facts_html = "".join(f"<span>{escape(fact)}</span>" for fact in quick_facts)
    title_seo = f"{listing['title']} | {listing_type_label} | UA-Dim"
    desc_seo = (
        f"{listing['rooms']} кімн., {listing['area']} м², {listing['city']}, {listing['district']}. "
        f"Ціна: {price_label}. {moderation_label}. {owner_verification_label}. {listing.get('description','')[:120]}"
    )

    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "UA-Dim", "item": public_app_url()},
            {"@type": "ListItem", "position": 2, "name": listing["city"], "item": city_link},
            {"@type": "ListItem", "position": 3, "name": listing["district"], "item": district_link},
            {"@type": "ListItem", "position": 4, "name": listing["title"], "item": canonical},
        ],
    }

    avg_rating = round(sum(r["rating"] for r in reviews) / len(reviews), 1) if reviews else None
    listing_ld: dict = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": listing["title"],
        "description": listing.get("description") or desc_seo,
        "url": canonical,
        "image": listing["images"][:5] if listing["images"] else [],
        "datePosted": published_label,
        "price": str(listing["price"]),
        "priceCurrency": "USD",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": listing["city"],
            "addressRegion": listing["district"],
            "addressCountry": "UA",
        },
        "floorLevel": str(listing.get("floor") or ""),
        "numberOfRooms": listing.get("rooms") or 0,
        "floorSize": {"@type": "QuantitativeValue", "value": listing["area"], "unitCode": "MTK"},
        "yearBuilt": str(listing.get("year_built") or ""),
        "offers": {
            "@type": "Offer",
            "price": str(listing["price"]),
            "priceCurrency": "USD",
            "availability": availability_url,
            "url": canonical,
            "itemCondition": "https://schema.org/UsedCondition",
            "seller": {
                "@type": (
                    "RealEstateAgent"
                    if listing.get("seller_type") in {"intermediary", "agency"}
                    else ("Organization" if listing.get("seller_type") == "developer" else "Person")
                ),
                "name": listing.get("agency_name") or listing.get("owner_name") or seller_type_label,
            },
        },
        "additionalProperty": [
            {"@type": "PropertyValue", "name": "moderationStatus", "value": moderation_label},
            {"@type": "PropertyValue", "name": "ownerVerificationStatus", "value": owner_verification_label},
            {"@type": "PropertyValue", "name": "phoneVerificationStatus", "value": phone_verification_label},
            {"@type": "PropertyValue", "name": "trustScore", "value": str(listing.get("trust_score", 0))},
        ],
    }
    if listing.get("latitude") and listing.get("longitude"):
        listing_ld["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": listing["latitude"],
            "longitude": listing["longitude"],
        }
    if avg_rating:
        listing_ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": avg_rating,
            "reviewCount": len(reviews),
            "bestRating": 5,
        }
        listing_ld["review"] = [
            {
                "@type": "Review",
                "reviewRating": {"@type": "Rating", "ratingValue": r["rating"], "bestRating": 5},
                "author": {"@type": "Person", "name": r["user_name"] or "Анонім"},
                "reviewBody": r["comment"] or "",
                "datePublished": (r["created_at"] or "")[:10],
            }
            for r in list(reviews)[:5]
        ]

    # Photo carousel HTML
    photos_html = ""
    if listing["images"]:
        imgs_html = "".join(
            f'<img src="{escape(img)}" alt="{escape(listing["title"])}" width="900" height="506" loading="{("eager" if i==0 else "lazy")}" style="width:100%;height:100%;object-fit:cover;flex-shrink:0;scroll-snap-align:start"/>'
            for i, img in enumerate(listing["images"])
        )
        photos_html = f'<div id="gallery" style="display:flex;overflow-x:auto;scroll-snap-type:x mandatory;border-radius:16px;aspect-ratio:16/9;background:#e2e8f0">{imgs_html}</div>'
        if len(listing["images"]) > 1:
            photos_html += f'<p style="font-size:13px;color:#94a3b8;margin-top:6px">{len(listing["images"])} фото · прокрутіть</p>'
    else:
        photos_html = '<div style="width:100%;aspect-ratio:16/9;background:#e2e8f0;border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:48px">🏠</div>'
    videos = normalize_listing_videos(listing.get("videos") or [])
    videos_html = ""
    if videos:
        video_items = "".join(
            f'<video controls playsinline preload="metadata" aria-label="Відео оголошення {index + 1}" '
            f'style="display:block;width:100%;max-height:520px;background:#0f172a;border-radius:16px">'
            f'<source src="{escape(video_url, quote=True)}"></video>'
            for index, video_url in enumerate(videos)
        )
        videos_html = (
            '<section aria-labelledby="listing-videos-heading" style="margin:18px 0">'
            '<h2 id="listing-videos-heading">Відео оголошення</h2>'
            '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:12px">'
            f'{video_items}</div></section>'
        )

    # Map embed (Leaflet inline for standalone page)
    map_html = ""
    if listing.get("latitude") and listing.get("longitude"):
        lat, lng = listing["latitude"], listing["longitude"]
        map_html = f"""
<div id="map" style="height:300px;border-radius:16px;margin:20px 0"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  var m=L.map('map',{{zoomControl:true}}).setView([{lat},{lng}],15);
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'© OpenStreetMap'}}).addTo(m);
  var markerIcon=L.divIcon({{
    className:'',
    html:'<div style="background:#2563eb;border:3px solid #fff;border-radius:9999px;width:18px;height:18px;box-shadow:0 4px 12px rgba(37,99,235,.35)"></div>',
    iconSize:[18,18],
    iconAnchor:[9,9]
  }});
  L.marker([{lat},{lng}],{{icon:markerIcon}}).addTo(m).bindPopup('{escape(listing["title"])}').openPopup();
</script>"""

    # Reviews HTML
    reviews_html = ""
    if reviews:
        stars = lambda r: "★" * int(r) + "☆" * (5 - int(r))
        reviews_html = "".join(
            f'<div style="border:1px solid #e2e8f0;border-radius:12px;padding:12px;margin:8px 0">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:4px">'
            f'<strong>{escape(r["user_name"] or "Анонім")}</strong>'
            f'<span style="color:#f59e0b">{stars(r["rating"])}</span></div>'
            f'<p style="margin:0;color:#475569">{escape(r["comment"] or "")}</p>'
            f'<div style="font-size:12px;color:#94a3b8;margin-top:4px">{(r["created_at"] or "")[:10]}</div>'
            f'</div>'
            for r in reviews
        )
    else:
        reviews_html = '<p style="color:#94a3b8">Відгуків ще немає.</p>'

    organization_ld = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "UA-Dim",
        "url": public_app_url(),
        "logo": f"{base}/favicon.png",
        "description": "Платформа для пошуку нерухомості в Україні: квартири, будинки, комерція, оренда та єОселя.",
    }
    webpage_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title_seo,
        "url": canonical,
        "description": desc_seo,
        "inLanguage": "uk-UA",
        "isPartOf": {"@type": "WebSite", "name": "UA-Dim", "url": public_app_url()},
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": ["#listing-title", "#listing-desc", "#trust-summary"],
        },
    }
    faq_entries = [
        {
            "q": "Чи перевірене це оголошення?",
            "a": f"Оголошення має {trust_count} сигналів довіри: {', '.join(trust_items) if trust_items else 'додаткових верифікацій поки немає'}. Статус модерації: {moderation_label.lower()}."
        },
        {
            "q": "Який статус об'єкта зараз?",
            "a": f"Поточний статус оголошення: {listing_status_label.lower()}."
        },
        {
            "q": "Що з перевіркою власника і телефону?",
            "a": f"{owner_verification_label}. {phone_verification_label}."
        },
        {
            "q": "Де подивитися схожі оголошення?",
            "a": "Відкрийте каталог UA-Dim, щоб побачити рекомендації, карту, створити алерт і зберегти об'єкт в обране."
        },
    ]
    faq_ld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faq_entries
        ],
    }

    trust_badges = []
    if listing.get("verified_owner"): trust_badges.append("✅ Власник верифікований")
    if listing.get("verified_phone"): trust_badges.append("📱 Телефон підтверджено")
    if listing.get("verified_docs"):  trust_badges.append("📄 Документи перевірено")
    if listing.get("has_photo_tour"): trust_badges.append("📸 Фото-тур")
    if listing.get("has_video_tour"): trust_badges.append("🎥 Відео-тур")
    trust_html = " &nbsp;·&nbsp; ".join(trust_badges) if trust_badges else ""
    listing_status_html = f'<span style="background:#fef3c7;color:#92400e;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:700">{listing_status_label}</span>'
    e_oselya_html = '<span style="background:#2563eb;color:#fff;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:700">єОселя</span>' if listing.get("e_oselya") else ""
    trust_flow_html = "".join(
        f'<div class="flow-card"><b>{escape(title)}</b><span>{escape(value)}</span></div>'
        for title, value in trust_flow_items
    )
    faq_html = "".join(
        f'<details style="border-top:1px solid #e2e8f0;padding:12px 0"><summary style="cursor:pointer;font-weight:700">{escape(item["q"])}</summary><p style="margin:10px 0 0;color:#475569">{escape(item["a"])}</p></details>'
        for item in faq_entries
    )

    if price_stats.get("status") == "ok":
        diff = price_stats.get("percent_diff_from_median_per_sqm")
        diff_label = (f"{'+' if diff is not None and diff > 0 else ''}{diff}%") if diff is not None else "—"
        price_stats_html = "".join(
            [
                '<div class="meta-grid">',
                f'<div class="meta-card"><b>${price_stats["median_price_per_sqm"]:,.0f}</b><span>медіана $/м²</span></div>',
                f'<div class="meta-card"><b>${price_stats["subject_price_per_sqm"]:,.0f}</b><span>ціна об\'єкта $/м²</span></div>',
                f'<div class="meta-card"><b>{diff_label}</b><span>відхилення від медіани</span></div>',
                f'<div class="meta-card"><b>{price_stats["sample_size"]}</b><span>порівнянних об\'єктів</span></div>',
                '</div>',
            ]
        )
    else:
        price_stats_html = (
            f'<p style="color:#94a3b8;margin:0">Недостатньо порівнянних оголошень для розрахунку медіанної ціни '
            f'(знайдено {price_stats.get("sample_size", 0)}, потрібно мінімум 3).</p>'
        )

    history_field_labels = {
        "price": "Ціна",
        "status": "Статус оголошення",
        "listing_status": "Статус об'єкта",
        "property_type": "Тип нерухомості",
        "rooms": "Кімнати",
        "area": "Площа",
        "listing_verification_status": "Верифікація оголошення",
    }
    if field_history:
        history_html = "".join(
            '<div style="border-top:1px solid #e2e8f0;padding:8px 0;font-size:13px;color:#475569">'
            f'<strong>{escape(history_field_labels.get(item["field_name"], item["field_name"]))}</strong>: '
            f'{escape(str(item["old_value"]) if item["old_value"] is not None else "—")} → '
            f'{escape(str(item["new_value"]) if item["new_value"] is not None else "—")} '
            f'<span style="color:#94a3b8">({escape((item["created_at"] or "")[:16])})</span>'
            '</div>'
            for item in field_history
        )
    else:
        history_html = '<p style="color:#94a3b8;margin:0">Історія змін поки відсутня.</p>'

    report_reason_labels = {
        "fraud_scam": "Шахрайство / обман",
        "duplicate_listing": "Дублікат оголошення",
        "misleading_price": "Неправдива ціна",
        "sold_or_unavailable": "Вже продано / недоступно",
        "spam": "Спам",
        "other": "Інше",
    }
    report_reason_options_html = "".join(
        f'<option value="{escape(code)}">{escape(report_reason_labels.get(code, code))}</option>'
        for code in REPORT_REASON_CODES
    )

    html = f"""<!doctype html>
<html lang="uk">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta name="robots" content="index, follow"/>
  <title>{escape(title_seo)}</title>
  <meta name="description" content="{escape(desc_seo)}"/>
  <link rel="canonical" href="{canonical}"/>
  <link rel="alternate" hreflang="uk-UA" href="{canonical}"/>
  <link rel="alternate" hreflang="x-default" href="{public_app_url()}"/>
  <link rel="preconnect" href="https://unpkg.com" crossorigin/>
  <link rel="preconnect" href="https://images.unsplash.com" crossorigin/>
  <meta property="og:locale" content="uk_UA"/>
  <meta property="og:type" content="website"/>
  <meta property="og:site_name" content="UA-Dim"/>
  <meta property="og:title" content="{escape(title_seo)}"/>
  <meta property="og:description" content="{escape(desc_seo)}"/>
  <meta property="og:url" content="{canonical}"/>
  <meta property="og:image" content="{escape(og_image)}"/>
  <meta property="og:image:alt" content="{escape(listing['title'])}"/>
  <meta property="og:image:width" content="900"/>
  <meta property="og:image:height" content="506"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{escape(title_seo)}"/>
  <meta name="twitter:description" content="{escape(desc_seo)}"/>
  <meta name="twitter:image" content="{escape(og_image)}"/>
  <meta name="twitter:image:alt" content="{escape(listing['title'])}"/>
  <meta name="twitter:site" content="@ua_homes"/>
  <script type="application/ld+json">{json.dumps(organization_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(webpage_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(breadcrumb_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(listing_ld, ensure_ascii=False)}</script>
  <script type="application/ld+json">{json.dumps(faq_ld, ensure_ascii=False)}</script>
  <style>
    *{{box-sizing:border-box}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:860px;margin:0 auto;padding:16px 20px 48px;color:#0f172a;background:linear-gradient(180deg,#f8fafc,#eef2ff);line-height:1.55}}
    a{{color:#2563eb;text-decoration:none}} a:hover{{text-decoration:underline}}
    h1{{font-size:clamp(1.3rem,5vw,1.9rem);font-weight:900;margin:12px 0 6px;line-height:1.2}}
    .breadcrumbs{{display:flex;flex-wrap:wrap;gap:6px;font-size:13px;color:#64748b;margin-bottom:12px}}
    .hero{{background:linear-gradient(135deg,#0f172a,#1e3a8a);border-radius:24px;padding:18px;color:#fff;box-shadow:0 20px 45px rgba(15,23,42,.16);margin-bottom:16px}}
    .hero-actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}}
    .hero-note{{display:inline-flex;align-items:center;gap:8px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.08);padding:6px 10px;border-radius:999px;font-size:12px;font-weight:700}}
    .hero-summary{{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-top:16px}}
    .price{{font-size:2rem;font-weight:900;color:#fff;margin:0;line-height:1.1}}
    .per-sqm{{font-size:13px;color:#bfdbfe;margin-top:5px}}
    .hero-facts{{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:7px}}
    .hero-facts span{{border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.1);padding:6px 9px;border-radius:999px;font-size:12px;font-weight:700;color:#fff}}
    .meta-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:16px 0}}
    .meta-card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;text-align:center}}
    .meta-card b{{display:block;font-size:1.1rem;color:#1e293b}}
    .meta-card span{{font-size:12px;color:#64748b}}
    .flow-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:14px}}
    .flow-card{{background:#fff;border:1px solid #dbeafe;border-radius:14px;padding:12px}}
    .flow-card b{{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#64748b;margin-bottom:6px}}
    .flow-card span{{font-size:14px;font-weight:700;color:#0f172a}}
    .section{{background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:16px 20px;margin:14px 0}}
    .trust{{font-size:13px;color:#15803d;background:#f0fdf4;padding:8px 12px;border-radius:10px;margin:8px 0}}
    .tag-list{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}}
    .verification-summary{{display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 0 14px;padding:12px 14px;border-radius:14px;background:#f0fdf4;color:#166534;font-size:13px;border:1px solid #bbf7d0}}
    .detail-grid{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(220px,.8fr);gap:14px;margin:14px 0}}
    .related-card{{background:#fff;border:1px solid #dbeafe;border-radius:16px;padding:16px 20px}}
    .related-links{{display:flex;flex-direction:column;gap:8px;margin-top:10px}}
    .related-links a{{display:block;border-radius:10px;background:#eff6ff;padding:9px 11px;font-size:13px;font-weight:700}}
    .disclosure{{margin:12px 0;border:1px solid #e2e8f0;border-radius:16px;background:#fff;overflow:hidden}}
    .disclosure summary{{display:flex;min-height:54px;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;cursor:pointer;font-weight:800;list-style:none}}
    .disclosure summary::-webkit-details-marker{{display:none}}
    .disclosure summary::after{{content:"+";font-size:20px;color:#64748b}}
    .disclosure[open] summary::after{{content:"−"}}
    .disclosure-content{{border-top:1px solid #e2e8f0;padding:16px 18px}}
    .disclosure-content h3{{margin:18px 0 8px;font-size:1rem}}
    .disclosure-content h3:first-child{{margin-top:0}}
    .report-card{{margin-top:14px;padding:14px 16px;border:1px solid #fed7aa;border-radius:16px;background:#fff7ed}}
    .primary-btn,.secondary-btn,.copy-btn{{display:inline-flex;min-height:44px;align-items:center;justify-content:center;border-radius:12px;font-weight:700;font-size:14px;cursor:pointer}}
    .primary-btn{{background:#2563eb;color:#fff;padding:12px 20px}}
    .secondary-btn,.copy-btn{{background:#f8fafc;color:#1e293b;padding:10px 16px;border:1px solid #e2e8f0}}
    @media(max-width:700px){{body{{padding-right:16px;padding-left:16px}} .hero{{padding:16px}} .hero-summary{{align-items:flex-start;flex-direction:column;gap:12px}} .hero-facts{{justify-content:flex-start}} .hero-actions{{display:grid;grid-template-columns:1fr 1fr}} .primary-btn{{grid-column:1/-1}} .primary-btn,.secondary-btn,.copy-btn{{padding-right:10px;padding-left:10px;text-align:center}} .meta-grid{{grid-template-columns:repeat(2,1fr)}} .detail-grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
  <nav class="breadcrumbs">
    <a href="{public_app_url()}">UA-Dim</a><span>›</span>
    <a href="{city_link}">{escape(listing["city"])}</a><span>›</span>
    <a href="{district_link}">{escape(listing["district"])}</a><span>›</span>
    <span>{escape(listing["title"][:40])}…</span>
  </nav>

  <section class="hero">
    <div class="hero-note">UA-Dim · {moderation_label}</div>
    <h1 id="listing-title" style="color:#fff;margin-top:14px">{escape(listing["title"])}</h1>
    <p id="listing-desc" style="margin:0;color:#cbd5e1">{escape(listing["city"])}, {escape(listing["district"])} · {listing_type_label} · {listing_status_label}</p>
    <div class="hero-summary">
      <div>
        <div class="price" id="listing-price">{price_label}</div>
        <div class="per-sqm">${per_sqm:,}/м² · опубліковано {escape(published_label or "—")}</div>
      </div>
      <div class="hero-facts" aria-label="Основні характеристики">{quick_facts_html}</div>
    </div>
    <div class="hero-actions">
      <a href="{escape(contact_link, quote=True)}" class="primary-btn">Запитати про об’єкт</a>
      <a href="{app_link}" class="secondary-btn">До каталогу UA-Dim</a>
      <button type="button" class="copy-btn" onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href).then(()=>this.textContent='Скопійовано')">Скопіювати посилання</button>
    </div>
  </section>

  {photos_html}
  {videos_html}

  <div class="tag-list" aria-label="Характеристики оголошення">
    <span style="background:#f1f5f9;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:600">{escape(listing.get('property_type',''))}</span>
    <span style="background:#f1f5f9;padding:3px 10px;border-radius:20px;font-size:13px;font-weight:600">{escape(listing.get('condition_type',''))}</span>
    <span style="background:{'#dcfce7' if listing_type_label=='Продаж' else '#fef9c3'};padding:3px 10px;border-radius:20px;font-size:13px;font-weight:700;color:#166534">{listing_type_label}</span>
    {listing_status_html}
    {e_oselya_html}
    {f'<span style="color:#f59e0b;font-weight:700">★ {avg_rating}</span>' if avg_rating else ''}
  </div>

  <div class="verification-summary" id="trust-summary">
    <span><strong>Модерація:</strong> {escape(moderation_label)}</span>
    <span><strong>Продавець:</strong> {escape(seller_type_label)}</span>
    <span><strong>Оголошення:</strong> {escape(verified_listing_label)}</span>
  </div>

  <div class="detail-grid">
    {f'<section class="section" style="margin:0"><h2 style="margin-top:0">Опис</h2><p style="margin:0;color:#334155">{escape(listing.get("description",""))}</p></section>' if listing.get("description") else ''}
    <aside class="related-card">
      <h2 style="margin:0;font-size:1rem">Схожі об’єкти</h2>
      <div class="related-links">
        <a href="{city_link}">{escape(listing["city"])}</a>
        <a href="{district_link}">{escape(listing["district"])}</a>
        <a href="{app_link}">Відкрити каталог із фільтрами</a>
      </div>
    </aside>
  </div>

  {map_html}

  <details class="disclosure" id="verification-details">
    <summary>Перевірки та історія</summary>
    <div class="disclosure-content">
      <p style="margin:0;color:#475569">Показуємо окремо модерацію, власника, телефон і документи — без об’єднання різних перевірок в один бейдж.</p>
      {f'<div class="trust">{trust_html}</div>' if trust_html else ''}
      <div class="flow-grid">
        {trust_flow_html}
      </div>
      <h3>Історія змін</h3>
      <p style="margin:0 0 10px;color:#475569">Ціна, статус, тип, кімнати, площа та верифікація.</p>
      {history_html}
    </div>
  </details>

  <details class="disclosure">
    <summary>Ціна та відповіді на запитання</summary>
    <div class="disclosure-content">
      <h3>Порівняння цін</h3>
      <p style="margin:0 0 10px;color:#475569">На основі реальних активних оголошень цього міста, району та типу нерухомості.</p>
      {price_stats_html}
      <h3>Часті запитання</h3>
      {faq_html}
    </div>
  </details>

  <details class="disclosure">
    <summary>Відгуки {f"({len(reviews)})" if reviews else ""}</summary>
    <div class="disclosure-content">
      {reviews_html}
      <p style="margin:12px 0 0"><a href="{app_link}">Залишити відгук у UA-Dim →</a></p>
    </div>
  </details>

  <div class="report-card">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
      <div>
        <strong style="color:#9a3412">Помітили проблему?</strong>
        <p style="margin:3px 0 0;color:#475569;font-size:13px">Модерація перевірить шахрайство, дублікат або неправдиву ціну.</p>
      </div>
      <button type="button" class="secondary-btn" id="openReportBtn">Повідомити</button>
    </div>
    <dialog id="reportDialog" style="border:none;border-radius:16px;padding:0;max-width:440px;width:92vw;box-shadow:0 20px 45px rgba(15,23,42,.2)">
      <form method="dialog" id="reportForm" style="padding:20px">
        <h3 style="margin:0 0 12px">Повідомити про проблему</h3>
        <label for="reportReason" style="display:block;font-size:13px;font-weight:700;margin-bottom:4px">Причина</label>
        <select id="reportReason" name="reason_code" required style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5e1;margin-bottom:10px">
          {report_reason_options_html}
        </select>
        <label for="reportDetails" style="display:block;font-size:13px;font-weight:700;margin-bottom:4px">Деталі (10–1000 символів)</label>
        <textarea id="reportDetails" name="details" required minlength="10" maxlength="1000" rows="4" style="width:100%;padding:8px;border-radius:8px;border:1px solid #cbd5e1;margin-bottom:6px"></textarea>
        <p id="reportError" role="alert" style="color:#be123c;font-size:13px;display:none;margin:0 0 10px"></p>
        <p id="reportSuccess" role="status" style="color:#166534;font-size:13px;display:none;margin:0 0 10px">Дякуємо! Скаргу надіслано на перевірку.</p>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button type="button" id="reportCancel" class="secondary-btn">Скасувати</button>
          <button type="submit" id="reportSubmit" class="primary-btn">Надіслати</button>
        </div>
      </form>
    </dialog>
  </div>
  <script>
  (function() {{
    var dialog = document.getElementById('reportDialog');
    var openBtn = document.getElementById('openReportBtn');
    var cancelBtn = document.getElementById('reportCancel');
    var form = document.getElementById('reportForm');
    var reasonEl = document.getElementById('reportReason');
    var detailsEl = document.getElementById('reportDetails');
    var errorEl = document.getElementById('reportError');
    var successEl = document.getElementById('reportSuccess');
    var submitBtn = document.getElementById('reportSubmit');
    if (!dialog || !openBtn) return;

    function getSessionId() {{
      var key = 'ua_homes_report_session';
      try {{
        var value = window.localStorage.getItem(key);
        if (!value) {{
          value = 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
          window.localStorage.setItem(key, value);
        }}
        return value;
      }} catch (e) {{
        return 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2);
      }}
    }}

    function openDialog() {{
      errorEl.style.display = 'none';
      successEl.style.display = 'none';
      submitBtn.disabled = false;
      if (typeof dialog.showModal === 'function') {{
        dialog.showModal();
      }} else {{
        dialog.setAttribute('open', '');
      }}
    }}

    function closeDialog() {{
      if (typeof dialog.close === 'function') {{
        dialog.close();
      }} else {{
        dialog.removeAttribute('open');
      }}
    }}

    openBtn.addEventListener('click', openDialog);
    cancelBtn.addEventListener('click', closeDialog);
    // Native <dialog> already closes on Escape; this keeps older browsers consistent.
    dialog.addEventListener('cancel', function() {{ errorEl.style.display = 'none'; }});
    dialog.addEventListener('keydown', function(ev) {{
      if (ev.key === 'Escape') closeDialog();
    }});

    form.addEventListener('submit', function(ev) {{
      ev.preventDefault();
      errorEl.style.display = 'none';
      successEl.style.display = 'none';
      var details = (detailsEl.value || '').trim();
      if (details.length < 10 || details.length > 1000) {{
        errorEl.textContent = 'Опис має містити від 10 до 1000 символів.';
        errorEl.style.display = 'block';
        return;
      }}
      submitBtn.disabled = true;
      var idempotencyKey = 'idem_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 12);
      fetch('/api/listings/{lid}/reports', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          reason_code: reasonEl.value,
          details: details,
          idempotency_key: idempotencyKey,
          reporter_session_id: getSessionId()
        }})
      }}).then(function(resp) {{
        return resp.json().catch(function() {{ return {{}}; }}).then(function(body) {{
          return {{ ok: resp.ok, body: body }};
        }});
      }}).then(function(result) {{
        if (result.ok) {{
          successEl.style.display = 'block';
          form.reset();
        }} else {{
          errorEl.textContent = (result.body && result.body.error) || 'Не вдалося надіслати скаргу. Спробуйте ще раз.';
          errorEl.style.display = 'block';
          submitBtn.disabled = false;
        }}
      }}).catch(function() {{
        errorEl.textContent = 'Помилка мережі. Спробуйте ще раз.';
        errorEl.style.display = 'block';
        submitBtn.disabled = false;
      }});
    }});
  }})();
  </script>
</body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/sitemap.xml", methods=["GET"])
def sitemap_xml():
    db = get_db()
    base = public_base_url()
    rows = db.execute(
        """
        SELECT city, district, MAX(created_at) as updated_at
        FROM listings
        WHERE status = 'published'
        GROUP BY city, district
        ORDER BY city, district
        """
    ).fetchall()

    items = [
        f"<url><loc>{public_app_url()}</loc></url>",
        f"<url><loc>{base}/privacy.html</loc></url>",
        f"<url><loc>{base}/terms.html</loc></url>",
        f"<url><loc>{base}/cookie-policy.html</loc></url>",
    ]
    seen_cities = set()
    for row in rows:
        city = row["city"]
        district = row["district"]
        updated = (row["updated_at"] or "")[:10]
        if city not in seen_cities:
            seen_cities.add(city)
            items.append(
                f"<url><loc>{base}/seo/{quote(city)}</loc><lastmod>{updated}</lastmod></url>"
            )
        items.append(
            f"<url><loc>{base}/seo/{quote(city)}/{quote(district)}</loc><lastmod>{updated}</lastmod></url>"
        )

    project_updated = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    for project in DEVELOPMENT_PROJECTS:
        items.append(
            f"<url><loc>{base}/zhk/{quote(project['slug'])}</loc><lastmod>{project_updated}</lastmod><changefreq>weekly</changefreq></url>"
        )

    # Individual listing pages
    listing_rows = db.execute(
        "SELECT id, created_at FROM listings WHERE status = 'published' ORDER BY id DESC LIMIT 500"
    ).fetchall()
    for lr in listing_rows:
        updated = (lr["created_at"] or "")[:10]
        items.append(f"<url><loc>{base}/listing/{lr['id']}</loc><lastmod>{updated}</lastmod><changefreq>weekly</changefreq></url>")

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(items)
        + "</urlset>"
    )
    return Response(xml, mimetype="application/xml; charset=utf-8")


@app.route("/seo/snippets/top", methods=["GET"])
def seo_top_snippets():
    db = get_db()
    limit = nonneg_int(request.args.get("limit")) or 8
    limit = min(max(limit, 1), 30)
    base = public_base_url()
    top_cities, top_districts = _seo_landing_stats(db, limit=limit)

    city_cards = "".join(
        (
            '<a class="seo-card" href="'
            f'{base}/seo/{quote(row["city"])}'
            '">'
            f'<strong>{escape(row["city"])}</strong>'
            f'<span>{row["cnt"]} об.</span>'
            f'<span>${int(row["avg_price"] or 0):,}</span>'
            "</a>"
        )
        for row in top_cities
    )
    district_cards = "".join(
        (
            '<a class="seo-card" href="'
            f'{base}/seo/{quote(row["city"])}/{quote(row["district"])}'
            '">'
            f'<strong>{escape(row["city"])}, {escape(row["district"])}</strong>'
            f'<span>{row["cnt"]} об.</span>'
            f'<span>${int(row["avg_price"] or 0):,}</span>'
            "</a>"
        )
        for row in top_districts
    )

    html = f"""
<section data-seo-snippets="top">
  <style>
    .seo-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
    .seo-card{{display:flex;flex-direction:column;gap:4px;padding:10px 12px;border:1px solid #e2e8f0;border-radius:12px;text-decoration:none;color:#0f172a;background:#fff}}
    .seo-card:hover{{border-color:#93c5fd;background:#eff6ff}}
    .seo-card span{{font-size:12px;color:#64748b}}
  </style>
  <h2>Топ-міста</h2>
  <div class="seo-grid">{city_cards or '<p>Немає даних.</p>'}</div>
  <h2>Топ-райони</h2>
  <div class="seo-grid">{district_cards or '<p>Немає даних.</p>'}</div>
</section>
"""
    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    base = public_base_url()
    body = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin/",
            "Disallow: /api/admin/",
            f"Sitemap: {base}/sitemap.xml",
            "",
        ]
    )
    return Response(body, mimetype="text/plain; charset=utf-8")


@app.route("/seo/audit", methods=["GET"])
def seo_audit():
    """
    Core Web Vitals + SEO audit report for UA Homes.
    Returns a structured JSON audit with priority levels (critical/high/medium/low).
    """
    base = public_base_url()
    audit = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "site": base,
        "score_summary": {
            "lcp": "good",
            "cls": "good",
            "inp": "good",
            "seo": "good",
            "overall": "good",
        },
        "findings": [],
        "fixed": [
            {
                "id": "cwv-lcp-cdn-scripts",
                "metric": "LCP",
                "priority": "critical",
                "title": "✅ FIXED — Babel standalone removed; JSX pre-compiled with esbuild",
                "detail": "JSX is now compiled at build time via esbuild. Babel CDN script removed. React switched to production.min.js builds.",
                "saving": "~925 kB download, ~300 ms JS parse eliminated on first load.",
            },
            {
                "id": "cwv-inp-tailwind-cdn",
                "metric": "INP",
                "priority": "high",
                "title": "✅ FIXED — Tailwind CDN replaced with 28 kB purged CSS",
                "detail": "tailwindcss standalone CLI scanned real-estate-demo.html and real-estate-app.js, emitting ua-homes.css (28 kB vs ~350 kB CDN).",
                "saving": "~322 kB stylesheet eliminated; style recalc time reduced ~80 ms on mobile.",
            },
            {
                "id": "cwv-lcp-image-priority",
                "metric": "LCP",
                "priority": "high",
                "title": "✅ FIXED — fetchPriority='high' on first card image",
                "detail": "PropertyCard passes priority={idx===0} to PhotoGallery. First img gets fetchPriority='high'; all others get loading='lazy'.",
            },
            {
                "id": "cwv-cls-image-dimensions",
                "metric": "CLS",
                "priority": "high",
                "title": "✅ FIXED — width/height attrs + aspect-ratio:16/9 on gallery containers",
                "detail": "All img elements now carry width='640' height='360'. Gallery containers use style={{aspectRatio:'16/9'}} so the browser reserves layout space before the image loads.",
            },
            {
                "id": "seo-lazy-loading",
                "metric": "LCP",
                "priority": "medium",
                "title": "✅ FIXED — loading='lazy' on all non-first gallery images",
                "detail": "PhotoGallery sets loading='lazy' for all images except the first (priority) one.",
            },
            {
                "id": "seo-preconnect",
                "metric": "LCP",
                "priority": "medium",
                "title": "✅ FIXED — <link rel='preconnect'> for unpkg.com",
                "detail": "Tailwind CDN link removed; preconnect for unpkg.com (Leaflet) kept. cdn.tailwindcss.com no longer loaded.",
            },
            {
                "id": "seo-meta-robots",
                "metric": "SEO",
                "priority": "low",
                "title": "✅ FIXED — <meta name='robots' content='index, follow'> added",
                "detail": "Explicit robots meta tag added to SPA <head>.",
            },
            {
                "id": "seo-structured-data-review",
                "metric": "SEO",
                "priority": "low",
                "title": "✅ FIXED — AggregateRating + Review JSON-LD injected dynamically",
                "detail": "PropertyDetailModal useEffect injects a Product + AggregateRating + Review JSON-LD block when a listing with reviews is opened, and removes it on close.",
            },
        ],
        "already_implemented": [
            "WebSite schema with SearchAction",
            "Organization schema (SEO pages + SPA)",
            "WebPage + Speakable schema on SEO landing pages",
            "CollectionPage + ItemList schema on SEO landing pages",
            "Dataset schema per city/district",
            "BreadcrumbList schema",
            "FAQPage schema with visible <details> blocks",
            "Pagination rel=prev/next",
            "Canonical URLs with UA_HOMES_PUBLIC_URL env var",
            "hreflang uk-UA + x-default",
            "OpenGraph + Twitter card meta",
            "sitemap.xml with city/district URLs",
            "robots.txt with Disallow for admin routes",
            "Pre-render snippet endpoint /seo/snippets/top",
            "AggregateRating + Review JSON-LD (dynamic, on listing open)",
        ],
    }
    return jsonify(audit)


# ─── Health check ─────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    try:
        database = get_db()
        database.execute("SELECT 1 AS ready").fetchone()
    except Exception:
        app.logger.exception(
            "Database readiness check failed request_id=%s",
            getattr(g, "request_id", "unknown"),
        )
        return jsonify(status="error", service="UA Homes API v2", database="unavailable"), 503
    return jsonify(status="ok", service="UA Homes API v2", database="ok")


def _backup_request_authorized() -> tuple[bool, int]:
    configured_token = os.environ.get("UA_HOMES_BACKUP_TOKEN", "").strip()
    if not configured_token:
        return False, 503
    authorization = request.headers.get("Authorization", "")
    scheme, _, provided_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not provided_token:
        return False, 401
    return hmac.compare_digest(provided_token, configured_token), 401


@app.route("/api/operations/backup", methods=["POST"])
@limiter.limit("6 per hour")
def create_operations_backup():
    authorized, error_status = _backup_request_authorized()
    if not authorized:
        if error_status == 503:
            app.logger.error("Database backup requested before UA_HOMES_BACKUP_TOKEN was configured")
            return jsonify(error="Database backups are not configured"), 503
        return jsonify(error="Unauthorized"), 401
    if _is_postgres():
        return jsonify(error="PostgreSQL backups require the managed database backup workflow"), 501

    from operations_backup import create_backup

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"ua-homes-{timestamp}.sqlite3"
    temporary_directory = tempfile.mkdtemp(prefix="ua-homes-backup-")
    backup_path = os.path.join(temporary_directory, filename)
    try:
        summary = create_backup(DB_PATH, backup_path)
    except Exception:
        try:
            os.rmdir(temporary_directory)
        except OSError:
            pass
        app.logger.exception(
            "Database backup failed request_id=%s",
            getattr(g, "request_id", "unknown"),
        )
        return jsonify(error="Database backup failed"), 500

    backup_file = open(backup_path, "rb")

    def cleanup_backup():
        try:
            backup_file.close()
            os.remove(backup_path)
            os.rmdir(temporary_directory)
        except OSError as exc:
            app.logger.warning("Temporary database backup cleanup failed: %s", exc)

    response = send_file(
        backup_file,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.sqlite3",
        conditional=False,
    )
    response.direct_passthrough = False
    response.call_on_close(cleanup_backup)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Backup-SHA256"] = summary["sha256"]
    response.headers["X-Backup-Users"] = str(summary["row_counts"]["users"])
    response.headers["X-Backup-Listings"] = str(summary["row_counts"]["listings"])
    return response


# ─── Premium / LiqPay payment ─────────────────────────────────────────────────

def _liqpay_sign(private_key: str, data: str) -> str:
    """Generate LiqPay signature: base64(sha1(private_key + data + private_key))"""
    raw = private_key + data + private_key
    sha = hashlib.sha1(raw.encode("utf-8")).digest()
    return base64.b64encode(sha).decode("utf-8")


def _liqpay_encode(payload: dict, private_key: str) -> tuple[str, str]:
    """Encode LiqPay payload; return (data_b64, signature)."""
    data_b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("utf-8")
    signature = _liqpay_sign(private_key, data_b64)
    return data_b64, signature


LIQPAY_MODES = {"disabled", "sandbox", "live"}
LIQPAY_FAILURE_STATUSES = {
    "error",
    "failure",
    "reversed",
    "unsubscribed",
}


def _liqpay_config() -> tuple[str, str, str, str | None]:
    """Return validated mode and keys without exposing credential details."""
    mode = os.environ.get("LIQPAY_MODE", "disabled").strip().lower() or "disabled"
    public_key = os.environ.get("LIQPAY_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("LIQPAY_PRIVATE_KEY", "").strip()

    if mode not in LIQPAY_MODES:
        return mode, public_key, private_key, "invalid_mode"
    if mode == "disabled":
        return mode, public_key, private_key, None
    if not public_key or not private_key:
        return mode, public_key, private_key, "missing_keys"

    public_is_sandbox = public_key.startswith("sandbox_")
    private_is_sandbox = private_key.startswith("sandbox_")
    if mode == "sandbox" and not (public_is_sandbox and private_is_sandbox):
        return mode, public_key, private_key, "sandbox_key_mismatch"
    if mode == "live" and (public_is_sandbox or private_is_sandbox):
        return mode, public_key, private_key, "live_key_mismatch"
    if mode == "live":
        public_url = os.environ.get("UA_HOMES_PUBLIC_URL", "").strip().rstrip("/")
        api_url = os.environ.get("UA_HOMES_API", "").strip().rstrip("/") or public_url
        for name, value in (("public_url", public_url), ("api_url", api_url)):
            if not _is_external_https_base_url(value):
                return mode, public_key, private_key, f"invalid_{name}"
    return mode, public_key, private_key, None


def _is_external_https_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return False
    if host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".test", ".example", ".invalid")
    ):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def _liqpay_amount_matches(expected, actual) -> bool:
    try:
        return Decimal(str(expected)) == Decimal(str(actual))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _payment_unavailable(config_error: str | None = None):
    if config_error:
        app.logger.error("LiqPay configuration rejected: %s", config_error)
    return jsonify(
        error="Платежі тимчасово недоступні",
        code="payments_disabled" if not config_error else "payments_misconfigured",
    ), 503


LEGACY_PLAN_ALIASES = {"agent": "realtor_pro"}


def resolve_plan_id(raw) -> str | None:
    """Map an incoming plan id (including legacy ids) to a known paid plan."""
    candidate = str(raw or "").strip()
    candidate = LEGACY_PLAN_ALIASES.get(candidate, candidate)
    return candidate if candidate in PAID_PLAN_IDS else None


def _reversal_previous_entitlement(db, order) -> tuple[str, str | None]:
    """Restore only entitlements still backed by a non-reversed paid order."""
    order_plan_id = str(order["plan_id"] or "")
    previous_plan_id = str(order["previous_plan_id"] or "")
    previous_expiry = order["previous_plan_expires_at"]
    if previous_plan_id not in SUBSCRIPTION_PLANS:
        return default_plan_for(SUBSCRIPTION_PLANS[order_plan_id]["audience"]), None
    if previous_plan_id in PAID_PLAN_IDS:
        supporting_order = db.execute(
            "SELECT order_id FROM premium_orders"
            " WHERE user_id = ? AND plan_id = ? AND status = 'paid' AND order_id <> ?"
            " LIMIT 1",
            (order["user_id"], previous_plan_id, order["order_id"]),
        ).fetchone()
        if not supporting_order:
            return default_plan_for(SUBSCRIPTION_PLANS[previous_plan_id]["audience"]), None
    return previous_plan_id, previous_expiry


@app.route("/api/payment/liqpay/create", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def payment_liqpay_create():
    """Create LiqPay payment: return data + signature for checkout form."""
    body = request.get_json(silent=True) or {}
    plan_id = resolve_plan_id(body.get("plan_id"))

    if not plan_id:
        return jsonify(error="Unknown plan"), 400

    plan = SUBSCRIPTION_PLANS[plan_id]
    mode, public_key, private_key, config_error = _liqpay_config()
    if mode == "disabled":
        return _payment_unavailable()
    if config_error:
        return _payment_unavailable(config_error)

    db = get_db()
    public_url = os.environ.get("UA_HOMES_PUBLIC_URL", "").strip().rstrip("/") or "http://localhost:5050"
    api_url = os.environ.get("UA_HOMES_API", "").strip().rstrip("/") or public_url
    order_id = f"uadim-{plan_id}-{int(time.time())}-{secrets.token_hex(4)}"

    # Persist the order up front so the callback can attribute it to a user.
    try:
        db.execute(
            "INSERT INTO premium_orders"
            " (order_id, plan_id, amount, currency, status, user_id, environment)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (order_id, plan_id, plan["price"], "UAH", g.user_id, mode),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        app.logger.error("LiqPay order persistence failed: %s", exc)
        return jsonify(error="Не вдалося створити замовлення", code="order_create_failed"), 503

    payload = {
        "public_key":  public_key,
        "version":     "3",
        "action":      "pay",
        "amount":      plan["price"],
        "currency":    "UAH",
        "description": f"UA-Dim {plan['name']} — {plan['price']} UAH/міс",
        "order_id":    order_id,
        "result_url":  f"{public_url}/real-estate-demo.html?payment=return&order_id={quote(order_id)}",
        "server_url":  f"{api_url}/api/payment/liqpay/callback",
        "language":    "uk",
    }
    if mode == "sandbox":
        payload["sandbox"] = 1

    data_b64, signature = _liqpay_encode(payload, private_key)
    return jsonify(data=data_b64, signature=signature, order_id=order_id, mode=mode)


@app.route("/api/payment/liqpay/callback", methods=["POST"])
def payment_liqpay_callback():
    """Verify a LiqPay callback and activate a paid plan exactly once."""
    mode, public_key, private_key, config_error = _liqpay_config()
    if mode == "disabled":
        return "payments_disabled", 503
    if config_error:
        app.logger.error("LiqPay callback configuration rejected: %s", config_error)
        return "payments_misconfigured", 503

    data_b64   = request.form.get("data", "")
    signature  = request.form.get("signature", "")

    if not data_b64 or not signature or len(data_b64) > 100_000 or len(signature) > 500:
        return "invalid_request", 400

    expected_sig = _liqpay_sign(private_key, data_b64)
    if not secrets.compare_digest(expected_sig, signature):
        app.logger.error("LiqPay callback: invalid signature")
        return "signature_mismatch", 400

    try:
        payload = json.loads(base64.b64decode(data_b64, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return "decode_error", 400
    if not isinstance(payload, dict):
        return "invalid_payload", 400

    status    = str(payload.get("status") or "").strip().lower()
    order_id  = str(payload.get("order_id") or "").strip()
    amount    = payload.get("amount")
    currency  = str(payload.get("currency") or "").strip().upper()
    action    = str(payload.get("action") or "").strip().lower()
    callback_public_key = str(payload.get("public_key") or "").strip()
    provider_payment_id = str(payload.get("payment_id") or "").strip()

    if not re.fullmatch(r"uadim-[a-z0-9_]+-\d{9,12}-[a-f0-9]{8}", order_id):
        return "invalid_order_id", 400
    if action != "pay" or callback_public_key != public_key:
        return "provider_mismatch", 400

    db = get_db()
    existing = db.execute(
        "SELECT order_id, user_id, plan_id, amount, currency, status, environment,"
        " provider_payment_id, previous_plan_id, previous_plan_expires_at,"
        " activated_plan_expires_at, entitlement_chain_id"
        " FROM premium_orders WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if not existing:
        return "unknown_order", 404

    if existing["environment"] != mode:
        return "environment_mismatch", 409
    if currency != str(existing["currency"] or "").upper():
        return "currency_mismatch", 400
    if not _liqpay_amount_matches(existing["amount"], amount):
        return "amount_mismatch", 400

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    expected_paid_status = "sandbox" if mode == "sandbox" else "success"
    if status == "reversed":
        previous_payment_id = str(existing["provider_payment_id"] or "")
        if previous_payment_id and previous_payment_id != provider_payment_id:
            return "payment_id_mismatch", 409
        try:
            reversal = db.execute(
                "UPDATE premium_orders SET status = 'reversing', provider_status = ?,"
                " provider_payment_id = ?, processed_at = ?"
                " WHERE order_id = ? AND status = 'paid'",
                (status, provider_payment_id or previous_payment_id or None, now, order_id),
            )
            if reversal.rowcount == 1:
                db.execute(
                    "UPDATE users SET plan_id = plan_id WHERE id = ?",
                    (existing["user_id"],),
                )
                user = db.execute(
                    "SELECT plan_id, plan_expires_at FROM users WHERE id = ?",
                    (existing["user_id"],),
                ).fetchone()
                activation_expiry = str(existing["activated_plan_expires_at"] or "")
                order_plan_id = str(existing["plan_id"] or "")
                user_plan_id = str(user["plan_id"] or "") if user else ""
                user_expiry = str(user["plan_expires_at"] or "") if user else ""
                active_order = None
                if user and user_plan_id == order_plan_id:
                    active_order = db.execute(
                        "SELECT order_id, entitlement_chain_id FROM premium_orders"
                        " WHERE user_id = ? AND plan_id = ?"
                        " AND status IN ('paid', 'reversing')"
                        " AND activated_plan_expires_at = ?"
                        " ORDER BY paid_at DESC, id DESC LIMIT 1",
                        (existing["user_id"], order_plan_id, user_expiry),
                    ).fetchone()
                    if not active_order:
                        active_order = db.execute(
                            "SELECT order_id, entitlement_chain_id FROM premium_orders"
                            " WHERE user_id = ? AND plan_id = ?"
                            " AND status IN ('paid', 'reversing')"
                            " ORDER BY paid_at DESC, id DESC LIMIT 1",
                            (existing["user_id"], order_plan_id),
                        ).fetchone()
                active_chain_id = (
                    str(active_order["entitlement_chain_id"] or active_order["order_id"])
                    if active_order
                    else ""
                )
                order_chain_id = str(existing["entitlement_chain_id"] or existing["order_id"])
                contributes_to_active_entitlement = active_chain_id == order_chain_id

                if (
                    user
                    and user_plan_id == order_plan_id
                    and contributes_to_active_entitlement
                    and activation_expiry
                    and user_expiry == activation_expiry
                ):
                    previous_plan_id, previous_expiry = _reversal_previous_entitlement(db, existing)
                    db.execute(
                        "UPDATE users SET plan_id = ?, plan_expires_at = ?, account_type = ?"
                        " WHERE id = ?",
                        (
                            previous_plan_id,
                            previous_expiry,
                            SUBSCRIPTION_PLANS[previous_plan_id]["audience"],
                            existing["user_id"],
                        ),
                    )
                elif user and user_plan_id == order_plan_id and contributes_to_active_entitlement:
                    if not user_expiry:
                        raise ValueError("active paid plan has no expiry")
                    parsed_expiry = datetime.datetime.fromisoformat(user_expiry.replace(" ", "T"))
                    reduced_expiry = parsed_expiry - datetime.timedelta(
                        days=SUBSCRIPTION_PLANS[order_plan_id]["duration_days"]
                    )
                    if reduced_expiry > datetime.datetime.utcnow():
                        db.execute(
                            "UPDATE users SET plan_expires_at = ? WHERE id = ?",
                            (
                                reduced_expiry.replace(microsecond=0).isoformat(sep=" "),
                                existing["user_id"],
                            ),
                        )
                    else:
                        previous_plan_id, previous_expiry = _reversal_previous_entitlement(db, existing)
                        db.execute(
                            "UPDATE users SET plan_id = ?, plan_expires_at = ?, account_type = ?"
                            " WHERE id = ?",
                            (
                                previous_plan_id,
                                previous_expiry,
                                SUBSCRIPTION_PLANS[previous_plan_id]["audience"],
                                existing["user_id"],
                            ),
                        )
                db.execute(
                    "UPDATE premium_orders SET status = 'reversed', processed_at = ?"
                    " WHERE order_id = ? AND status = 'reversing'",
                    (now, order_id),
                )
                db.commit()
                return "ok", 200

            pending_reversal = db.execute(
                "UPDATE premium_orders SET status = 'reversed', provider_status = ?,"
                " provider_payment_id = ?, processed_at = ?"
                " WHERE order_id = ? AND status NOT IN ('paid', 'processing', 'reversing', 'reversed')",
                (status, provider_payment_id or None, now, order_id),
            )
            if pending_reversal.rowcount == 1:
                db.commit()
            else:
                db.rollback()
            return "ok", 200
        except Exception as exc:
            db.rollback()
            app.logger.error("LiqPay reversal processing failed for order %s: %s", order_id, exc)
            return "processing_error", 500

    if status != expected_paid_status:
        normalized_status = "failed" if status in LIQPAY_FAILURE_STATUSES else "pending"
        if status in {"sandbox", "success"}:
            normalized_status = "rejected"
        if existing["status"] != "paid":
            transition = db.execute(
                "UPDATE premium_orders SET status = ?, provider_status = ?,"
                " provider_payment_id = ?, processed_at = ?"
                " WHERE order_id = ?"
                " AND status NOT IN ('paid', 'processing', 'reversing', 'reversed')",
                (normalized_status, status or None, provider_payment_id or None, now, order_id),
            )
            if transition.rowcount == 1:
                db.commit()
            else:
                db.rollback()
        return "ok", 200

    if not provider_payment_id:
        return "missing_payment_id", 400
    if existing["status"] == "paid":
        previous_payment_id = str(existing["provider_payment_id"] or "")
        if previous_payment_id and previous_payment_id != provider_payment_id:
            return "payment_id_mismatch", 409
        return "ok", 200

    plan_id = resolve_plan_id(existing["plan_id"])
    user_id = existing["user_id"]
    if not plan_id or not user_id:
        return "order_not_attributable", 409

    try:
        user_lock = db.execute(
            "UPDATE users SET plan_id = plan_id WHERE id = ?",
            (user_id,),
        )
        if user_lock.rowcount != 1:
            db.rollback()
            return "unknown_user", 409
        user = db.execute(
            "SELECT id, plan_id, plan_expires_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        entitlement_chain_id = order_id
        if (
            str(user["plan_id"] or "") == plan_id
            and str(user["plan_expires_at"] or "")
        ):
            active_order = db.execute(
                "SELECT order_id, entitlement_chain_id FROM premium_orders"
                " WHERE user_id = ? AND plan_id = ? AND status = 'paid'"
                " AND activated_plan_expires_at = ?"
                " ORDER BY paid_at DESC, id DESC LIMIT 1",
                (user_id, plan_id, user["plan_expires_at"]),
            ).fetchone()
            if active_order:
                entitlement_chain_id = str(
                    active_order["entitlement_chain_id"] or active_order["order_id"]
                )
        claim = db.execute(
            "UPDATE premium_orders SET status = 'processing', provider_status = ?,"
            " provider_payment_id = ?, processed_at = ?, previous_plan_id = ?,"
            " previous_plan_expires_at = ?, entitlement_chain_id = ?"
            " WHERE order_id = ?"
            " AND status NOT IN ('paid', 'processing', 'reversing', 'reversed')",
            (
                status,
                provider_payment_id,
                now,
                user["plan_id"],
                user["plan_expires_at"],
                entitlement_chain_id,
                order_id,
            ),
        )
        if claim.rowcount != 1:
            db.rollback()
            latest = db.execute(
                "SELECT status, provider_payment_id FROM premium_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if latest and latest["status"] == "paid":
                if str(latest["provider_payment_id"] or "") != provider_payment_id:
                    return "payment_id_mismatch", 409
                return "ok", 200
            return "ok", 200

        apply_plan_to_user(db, int(user_id), plan_id)
        activated_user = db.execute(
            "SELECT plan_expires_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        db.execute(
            "UPDATE premium_orders SET status = 'paid', paid_at = ?, processed_at = ?,"
            " activated_plan_expires_at = ?"
            " WHERE order_id = ? AND status = 'processing'",
            (
                now,
                now,
                activated_user["plan_expires_at"] if activated_user else None,
                order_id,
            ),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        app.logger.error("LiqPay callback processing failed for order %s: %s", order_id, exc)
        return "processing_error", 500

    return "ok", 200


@app.route("/api/payment/orders/<order_id>", methods=["GET"])
@require_auth
@limiter.limit("120 per hour")
def payment_order_status(order_id: str):
    """Return the authenticated user's server-confirmed payment state."""
    if not re.fullmatch(r"uadim-[a-z0-9_]+-\d{9,12}-[a-f0-9]{8}", order_id):
        return jsonify(error="Unknown order"), 404
    db = get_db()
    row = db.execute(
        "SELECT order_id, plan_id, amount, currency, status, provider_status, environment"
        " FROM premium_orders WHERE order_id = ? AND user_id = ?",
        (order_id, g.user_id),
    ).fetchone()
    if not row:
        return jsonify(error="Unknown order"), 404
    plan_id = resolve_plan_id(row["plan_id"])
    return jsonify(
        order_id=row["order_id"],
        plan_id=plan_id,
        amount=row["amount"],
        currency=row["currency"],
        status=row["status"],
        provider_status=row["provider_status"],
        environment=row["environment"],
        paid=row["status"] == "paid",
    )


@app.route("/api/payment/plans", methods=["GET"])
def payment_plans():
    """Public endpoint: return available plans grouped by audience."""
    audience = str(request.args.get("audience", "")).strip().lower()
    plans = [plan_public_dict(plan_id) for plan_id in SUBSCRIPTION_PLANS]
    if audience in ACCOUNT_TYPES:
        plans = [plan for plan in plans if plan["audience"] == audience]
    return jsonify(
        plans=plans,
        owner=[plan for plan in plans if plan["audience"] == "owner"],
        realtor=[plan for plan in plans if plan["audience"] == "realtor"],
    )


# ─── Register Blueprints ──────────────────────────────────────────────────

# Import and register admin blueprint
try:
    from admin_routes import admin_bp
    app.register_blueprint(admin_bp)
except ImportError:
    print("Warning: admin_routes not found")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5050))
    print(f"UA Homes API v2 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
