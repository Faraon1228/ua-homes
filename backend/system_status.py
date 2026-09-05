"""Bounded, privacy-safe operational status collection for staff and schedulers."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import threading
import time
from html import escape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

STATUSES = frozenset({"ok", "degraded", "down", "unknown", "not_configured"})
MAX_BODY_BYTES = 64 * 1024
_CACHE: dict[str, Any] = {}
_CACHE_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request: Request, timeout: int):
    return build_opener(_NoRedirect).open(request, timeout=timeout)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _seconds(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(max(int(os.environ.get(name, default)), minimum), maximum)
    except (TypeError, ValueError):
        return default


def _safe_https_url(value: str, allowed_hosts: set[str] | None = None) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or (allowed_hosts and host not in allowed_hosts):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_text(value: Any, limit: int = 160) -> str:
    text = _EMAIL_RE.sub("[redacted]", str(value or ""))
    text = re.sub(r"(?i)(token|secret|authorization|cookie)\s*[:=]\s*\S+", r"\1=[redacted]", text)
    return " ".join(text.split())[:limit]


def _parse_timestamp(value: Any) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed


def _http_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, Any, int]:
    """Fetch a bounded JSON response without following redirects."""
    started = time.monotonic()
    request = Request(url, headers=headers or {"Accept": "application/json"})
    try:
        with _open(request, _seconds("UA_HOMES_STATUS_TIMEOUT_SECONDS", 4, 1, 10)) as response:
            status = int(response.status)
            body = response.read(MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES:
                raise ValueError("provider response exceeded size limit")
    except HTTPError as exc:
        return exc.code, None, round((time.monotonic() - started) * 1000)
    except (URLError, TimeoutError, ValueError, OSError):
        return 0, None, round((time.monotonic() - started) * 1000)
    try:
        return status, json.loads(body.decode("utf-8")), round((time.monotonic() - started) * 1000)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None, round((time.monotonic() - started) * 1000)


def _component(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status if status in STATUSES else "unknown", **values}


def _website() -> dict[str, Any]:
    configured = _safe_https_url(os.environ.get("UA_HOMES_STATUS_WEBSITE_URL", ""))
    if not configured:
        return _component("not_configured")
    expected_host = (urlsplit(configured).hostname or "").lower()
    marker = os.environ.get("UA_HOMES_STATUS_WEBSITE_MARKER", "").strip()
    started = time.monotonic()
    try:
        request = Request(configured, headers={"User-Agent": "UA-Homes-status/1", "Accept": "text/html"})
        with _open(request, _seconds("UA_HOMES_STATUS_TIMEOUT_SECONDS", 4, 1, 10)) as response:
            status = int(response.status)
            body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("website response exceeded size limit")
    except HTTPError as exc:
        status, body = exc.code, b""
    except (URLError, TimeoutError, ValueError, OSError):
        status, body = 0, b""
    latency = round((time.monotonic() - started) * 1000)
    if not 200 <= status < 400:
        return _component("down" if status else "unknown", latency_ms=latency)
    if marker and marker.encode("utf-8") not in body:
        return _component("degraded", latency_ms=latency, canonical_host=expected_host, detail="expected_marker_missing")
    return _component("ok", latency_ms=latency, canonical_host=expected_host)


def _database(db) -> dict[str, Any]:
    started = time.monotonic()
    try:
        db.execute("SELECT 1").fetchone()
        from app import _is_postgres
        return _component("ok", engine="postgresql" if _is_postgres() else "sqlite",
                          latency_ms=round((time.monotonic() - started) * 1000))
    except Exception:
        return _component("down", latency_ms=round((time.monotonic() - started) * 1000))


def _api(database: dict[str, Any]) -> dict[str, Any]:
    # This is the same readiness dependency as /api/health, evaluated in-process.
    return _component("ok" if database["status"] == "ok" else "down",
                      contract="/api/health", database=database["status"])


def _push(db) -> dict[str, Any]:
    firebase = bool(os.environ.get("UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64", "").strip())
    webhook = bool(_safe_https_url(os.environ.get("UA_HOMES_ALERTS_PUSH_WEBHOOK_URL", "")))
    if not firebase and not webhook:
        return _component("not_configured", configured=False)
    try:
        row = db.execute(
            "SELECT success, finished_at, started_at FROM alert_dispatch_runs "
            "WHERE dry_run = 0 ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return _component("unknown", configured=True, detail="no_dispatch_history")
    value = dict(row) if not isinstance(row, dict) else row
    finished = value.get("finished_at") or value.get("started_at")
    timestamp = _parse_timestamp(finished)
    age = (dt.datetime.now(dt.timezone.utc) - timestamp).total_seconds() if timestamp else float("inf")
    success = bool(value.get("success"))
    stale = age > _seconds("UA_HOMES_STATUS_PUSH_STALE_SECONDS", 86400, 300, 604800)
    return _component("ok" if success and not stale else "degraded",
                      configured=True, last_success_at=finished if success else None,
                      stale=stale, last_run_success=success)


def _sentry() -> dict[str, Any]:
    token = os.environ.get("SENTRY_API_TOKEN", "").strip()
    org = os.environ.get("SENTRY_ORG", "").strip()
    projects = [p.strip() for p in os.environ.get("SENTRY_STATUS_PROJECTS", "").split(",") if p.strip()][:10]
    base = _safe_https_url(os.environ.get("SENTRY_BASE_URL", "https://sentry.io"))
    if not token or not org or not projects or not base:
        return _component("not_configured", critical_new_count=None, recent_issues=[], open_url=None)
    host = urlsplit(base).hostname
    endpoint = f"{base}/api/0/organizations/{quote(org, safe='')}/issues/?query=is%3Aunresolved%20(level%3Afatal%20or%20level%3Aerror)&limit=25"
    status, payload, _latency = _http_json(endpoint, {"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if status != 200 or not isinstance(payload, list):
        return _component("unknown" if status == 0 else "degraded", critical_new_count=None, recent_issues=[], open_url=None)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=_seconds("UA_HOMES_STATUS_SENTRY_LOOKBACK_HOURS", 24, 1, 168))
    issues = []
    for issue in payload[:25]:
        if not isinstance(issue, dict) or str(issue.get("project", {}).get("slug", "")) not in projects:
            continue
        first_seen = str(issue.get("firstSeen") or "")
        try:
            recent = dt.datetime.fromisoformat(first_seen.replace("Z", "+00:00")) >= cutoff
        except ValueError:
            recent = False
        if not recent:
            continue
        candidate = _safe_https_url(str(issue.get("permalink") or ""), {host} if host else None)
        issues.append({"title": _safe_text(issue.get("title"), 120), "type": _safe_text(issue.get("type"), 80),
                       "project": _safe_text(issue.get("project", {}).get("slug"), 80),
                       "first_seen": first_seen[:40], "url": candidate})
    return _component("ok", critical_new_count=len(issues), recent_issues=issues[:10],
                      open_url=_safe_https_url(f"{base}/organizations/{quote(org, safe='')}/issues/", {host} if host else None))


def _deployments() -> dict[str, Any]:
    token = os.environ.get("GITHUB_STATUS_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_STATUS_REPOSITORY", "").strip()
    if not token or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        return _component("not_configured", recent_failures=[], frontend_version=None)
    endpoint = f"https://api.github.com/repos/{repository}/actions/workflows/deploy.yml/runs?per_page=10"
    status, payload, _latency = _http_json(endpoint, {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if status != 200 or not isinstance(payload, dict):
        return _component("unknown" if status == 0 else "degraded", recent_failures=[], frontend_version=None)
    failures, frontend_version = [], None
    for run in payload.get("workflow_runs", [])[:10]:
        if not isinstance(run, dict):
            continue
        conclusion = str(run.get("conclusion") or "")
        safe_url = _safe_https_url(str(run.get("html_url") or ""), {"github.com"})
        if conclusion == "success" and not frontend_version:
            frontend_version = _safe_text(run.get("head_sha"), 64)
        if conclusion in {"failure", "cancelled", "timed_out"}:
            failures.append({"conclusion": conclusion, "sha": _safe_text(run.get("head_sha"), 64),
                             "created_at": str(run.get("created_at") or "")[:40], "url": safe_url})
    return _component("degraded" if failures else "ok", recent_failures=failures, frontend_version=frontend_version)


def collect(db) -> dict[str, Any]:
    database = _database(db)
    deployments = _deployments()
    backend_version = _safe_text(os.environ.get("SENTRY_RELEASE") or os.environ.get("RAILWAY_GIT_COMMIT_SHA"), 64) or None
    frontend_version = deployments.get("frontend_version")
    version_status = "unknown" if not backend_version or not frontend_version else ("ok" if backend_version == frontend_version else "degraded")
    components = {
        "website": _website(), "api": _api(database), "database": database, "push": _push(db),
        "sentry": _sentry(), "deployments": deployments,
    }
    states = [value["status"] for value in components.values()]
    overall = "down" if "down" in states else "degraded" if "degraded" in states else "unknown" if "unknown" in states else "ok"
    if version_status == "degraded" and overall == "ok":
        overall = "degraded"
    return {"contract_version": 1, "overall_status": overall, "generated_at": _now(), "stale": False,
            "components": components,
            "production_version": {"backend": backend_version, "frontend": frontend_version, "status": version_status},
            "notification_channels": {"email_configured": bool(os.environ.get("SENDGRID_API_KEY") or os.environ.get("SMTP_HOST")),
                                      "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and re.fullmatch(r"-?\d+", os.environ.get("TELEGRAM_CHAT_ID", "")))}} 


def _snapshot(db, data: dict[str, Any], duration_ms: int) -> None:
    db.execute("INSERT INTO system_status_snapshots (generated_at, overall_status, snapshot_json, refresh_duration_ms) VALUES (?, ?, ?, ?)",
               (data["generated_at"], data["overall_status"], json.dumps(data, ensure_ascii=True, separators=(",", ":")), duration_ms))
    db.execute(
        "DELETE FROM system_status_snapshots WHERE id NOT IN "
        "(SELECT id FROM system_status_snapshots ORDER BY id DESC LIMIT 100)"
    )
    db.commit()


def current_snapshot(db) -> dict[str, Any] | None:
    ttl = _seconds("UA_HOMES_STATUS_TTL_SECONDS", 300, 30, 3600)
    with _CACHE_LOCK:
        cached = _CACHE.get("snapshot")
        if cached and time.monotonic() - cached[0] <= ttl:
            return cached[1]
    row = db.execute("SELECT generated_at, snapshot_json FROM system_status_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    values = dict(row) if not isinstance(row, dict) else row
    try:
        snapshot = json.loads(values["snapshot_json"])
        generated = _parse_timestamp(values["generated_at"])
        if not generated:
            return None
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    if (dt.datetime.now(dt.timezone.utc) - generated).total_seconds() > ttl:
        snapshot["stale"] = True
        snapshot["overall_status"] = "unknown"
        return snapshot
    with _CACHE_LOCK:
        _CACHE["snapshot"] = (time.monotonic(), snapshot)
    return snapshot


def _incident_updates(db, data: dict[str, Any], notify: bool) -> None:
    for name, component in data["components"].items():
        status = component["status"]
        severity = "critical" if status == "down" else "warning"
        fingerprint = hashlib.sha256(name.encode()).hexdigest()[:40]
        row = db.execute(
            "SELECT id, status, severity, summary, notified_at FROM system_incidents WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        row_values = dict(row) if row else None
        summary = _safe_text(component.get("detail") or status)
        if status in {"ok", "not_configured"}:
            if row_values and row_values["status"] == "open":
                db.execute(
                    "UPDATE system_incidents SET status = 'resolved', last_seen_at = ?, resolved_at = ? WHERE id = ?",
                    (data["generated_at"], data["generated_at"], row_values["id"]),
                )
                if notify and row_values["severity"] == "critical":
                    _notify_incident(db, fingerprint, name, "recovery", "service recovered", data)
            continue
        if row_values:
            db.execute(
                "UPDATE system_incidents SET status = 'open', severity = ?, summary = ?, "
                "last_seen_at = ?, resolved_at = NULL WHERE id = ?",
                (severity, summary, data["generated_at"], row_values["id"]),
            )
        else:
            db.execute("INSERT INTO system_incidents (fingerprint, component, severity, summary, first_seen_at, last_seen_at, status) VALUES (?, ?, ?, ?, ?, ?, 'open')",
                       (fingerprint, name, severity, summary, data["generated_at"], data["generated_at"]))
            row_values = None
        if notify and severity == "critical" and _notification_due(row_values):
            _notify_incident(db, fingerprint, name, severity, summary, data)
    db.commit()


def _notification_due(row: dict[str, Any] | None) -> bool:
    if not row or not row.get("notified_at"):
        return True
    try:
        previous = _parse_timestamp(row["notified_at"])
        if not previous:
            return True
        return (dt.datetime.now(dt.timezone.utc) - previous).total_seconds() >= _seconds(
            "UA_HOMES_STATUS_NOTIFICATION_COOLDOWN_SECONDS", 900, 60, 86400
        )
    except (TypeError, ValueError):
        return True


def _notify_incident(db, fingerprint: str, component: str, severity: str, summary: str, data: dict[str, Any]) -> None:
    from app import _send_email
    links = []
    admin_url = _safe_https_url(os.environ.get("UA_HOMES_ADMIN_URL", ""))
    if admin_url:
        links.append(f"Admin: {admin_url}")
    sentry_url = data["components"].get("sentry", {}).get("open_url")
    if sentry_url:
        links.append(f"Sentry: {sentry_url}")
    deployment_url = next(
        (item.get("url") for item in data["components"].get("deployments", {}).get("recent_failures", []) if item.get("url")),
        None,
    )
    if deployment_url:
        links.append(f"GitHub: {deployment_url}")
    message = (
        f"UA Homes incident: {component} ({severity}) at {data['generated_at']}. "
        f"{summary}. Backend: {data['production_version']['backend'] or 'unknown'}."
        + (f" {' '.join(links)}" if links else "")
    )
    results = {}
    recipients = [value.strip() for value in os.environ.get("UA_HOMES_INCIDENT_EMAILS", "").split(",") if "@" in value][:20]
    if recipients:
        results["email"] = all(
            [_send_email(address, f"[UA Homes] {component} {severity}", message, f"<p>{escape(message)}</p>")
             for address in recipients]
        )
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and re.fullmatch(r"-?\d+", chat_id):
        try:
            request = Request(f"https://api.telegram.org/bot{token}/sendMessage",
                              data=json.dumps({"chat_id": chat_id, "text": message[:3500]}).encode(),
                              headers={"Content-Type": "application/json"}, method="POST")
            with _open(request, _seconds("UA_HOMES_STATUS_TIMEOUT_SECONDS", 4, 1, 10)) as response:
                results["telegram"] = 200 <= response.status < 300
        except (URLError, OSError, ValueError):
            results["telegram"] = False
    db.execute("UPDATE system_incidents SET notified_at = ?, notification_result = ? WHERE fingerprint = ?",
               (_now(), json.dumps(results, separators=(",", ":")), fingerprint))


def refresh(db, *, notify: bool = False) -> tuple[dict[str, Any] | None, bool]:
    if not _REFRESH_LOCK.acquire(blocking=False):
        return current_snapshot(db), False
    try:
        started = time.monotonic()
        data = collect(db)
        _snapshot(db, data, round((time.monotonic() - started) * 1000))
        _incident_updates(db, data, notify)
        with _CACHE_LOCK:
            _CACHE["snapshot"] = (time.monotonic(), data)
        return data, True
    finally:
        _REFRESH_LOCK.release()


def operations_authorized(provided: str) -> bool:
    configured = os.environ.get("UA_HOMES_STATUS_REFRESH_KEY", "").strip()
    return bool(configured and provided and hmac.compare_digest(provided, configured))
