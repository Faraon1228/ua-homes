import datetime
import hashlib
import hmac
import os
import sys
import tempfile
from flask import Blueprint, current_app, g, jsonify, request, send_file

system_bp = Blueprint("system_bp", __name__)


def _get_app_module():
    """Dynamically get the main app module to access shared globals and helpers."""
    if "backend.app" in sys.modules:
        return sys.modules["backend.app"]
    if "app" in sys.modules:
        return sys.modules["app"]
    try:
        import app
        return app
    except ImportError:
        from backend import app
        return app


@system_bp.route("/api/health", methods=["GET"])
def health():
    app_module = _get_app_module()
    is_pg = getattr(app_module, "_is_postgres", lambda: False)()
    engine = "postgresql" if is_pg else "sqlite"
    get_db = getattr(app_module, "get_db", None)

    try:
        database = get_db()
        database.execute("SELECT 1 AS ready").fetchone()
    except Exception:
        current_app.logger.exception(
            "Database readiness check failed request_id=%s",
            getattr(g, "request_id", "unknown"),
        )
        return jsonify(
            status="error",
            service="UA Homes API v2",
            database="unavailable",
            database_engine=engine,
        ), 503

    s3_bucket = getattr(app_module, "S3_BUCKET", "")
    cloudinary_url = getattr(app_module, "CLOUDINARY_URL", "")
    redis_url = getattr(app_module, "REDIS_URL", "")
    trusted_proxies = getattr(app_module, "TRUSTED_PROXY_NETWORKS", [])
    sentry_enabled = getattr(app_module, "SENTRY_ENABLED", False)
    monitoring_state = getattr(app_module, "monitoring_state", lambda: {})
    maintenance_mode = getattr(app_module, "MAINTENANCE_MODE", False)

    return jsonify(
        status="ok",
        service="UA Homes API v2",
        database="ok",
        database_engine=engine,
        media_storage=(
            "s3" if s3_bucket else "cloudinary" if cloudinary_url else "unconfigured"
        ),
        distributed_rate_limits=bool(redis_url),
        trusted_proxy_forwarding=bool(trusted_proxies),
        max_request_bytes=current_app.config["MAX_CONTENT_LENGTH"],
        error_monitoring=sentry_enabled,
        monitoring=monitoring_state(),
        maintenance_mode=maintenance_mode,
    )


def _backup_request_authorized() -> tuple[bool, int]:
    configured_token = os.environ.get("UA_HOMES_BACKUP_TOKEN", "").strip()
    if not configured_token:
        return False, 503
    authorization = request.headers.get("Authorization", "")
    scheme, _, provided_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not provided_token:
        return False, 401
    return hmac.compare_digest(provided_token, configured_token), 401


@system_bp.route("/api/operations/backup", methods=["POST"])
def create_operations_backup():
    app_module = _get_app_module()
    limiter = getattr(app_module, "limiter", None)

    authorized, error_status = _backup_request_authorized()
    if not authorized:
        if error_status == 503:
            current_app.logger.error("Database backup requested before UA_HOMES_BACKUP_TOKEN was configured")
            return jsonify(error="Database backups are not configured"), 503
        return jsonify(error="Unauthorized"), 401

    is_pg = getattr(app_module, "_is_postgres", lambda: False)()
    if is_pg:
        return jsonify(error="PostgreSQL backups require the managed database backup workflow"), 501

    try:
        from operations_backup import create_backup
    except ImportError:
        from backend.operations_backup import create_backup

    db_path = getattr(app_module, "DB_PATH", "backend/database.sqlite")
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"ua-homes-{timestamp}.sqlite3"
    temporary_directory = tempfile.mkdtemp(prefix="ua-homes-backup-")
    backup_path = os.path.join(temporary_directory, filename)
    try:
        summary = create_backup(db_path, backup_path)
    except Exception:
        try:
            os.rmdir(temporary_directory)
        except OSError:
            pass
        current_app.logger.exception(
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
            current_app.logger.warning("Temporary database backup cleanup failed: %s", exc)

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


@system_bp.route("/api/operations/system-status/refresh", methods=["POST"])
def refresh_operations_system_status():
    """Scheduler-only refresh; provider tokens and results remain server-side."""
    app_module = _get_app_module()
    try:
        from system_status import operations_authorized, refresh
    except ImportError:
        from backend.system_status import operations_authorized, refresh

    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not operations_authorized(token):
        return jsonify(error="Unauthorized"), 401

    get_db = getattr(app_module, "get_db", None)
    snapshot, refreshed = refresh(get_db(), notify=True)
    if snapshot is None:
        return jsonify(error="System status refresh is already in progress"), 429
    return jsonify(
        overall_status=snapshot["overall_status"],
        generated_at=snapshot["generated_at"],
        refresh_started=refreshed,
    ), 200 if refreshed else 429
