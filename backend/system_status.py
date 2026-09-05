"""Backend-only aggregation for the staff system status dashboard."""

from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


VALID_STATUSES = {"ok", "degraded", "down", "unknown", "not_configured"}
_SLUG = re.compile(r"^[A-Za-z0-9_.-]+$")
_DEFAULT_TTL_SECONDS = 900
_MAX_ISSUES = 10
_MAX_RUNS = 5


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


def _iso(value):
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_int(name, default, minimum=1, maximum=3600):
    try:
        return max(minimum, min(maximum, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def _request_json(url, *, headers=None):
    headers = dict(headers or {})
    hostname = urllib.parse.urlsplit(url).hostname
    if hostname == "sentry.io":
        headers["Authorization"] = "Bearer " + os.environ.get("UA_HOMES_SENTRY_API_TOKEN", "")
    elif hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + os.environ.get("UA_HOMES_GITHUB_TOKEN", "")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "UA-Dim-system-status/1", **headers},
    )
    timeout = _env_int("UA_HOMES_STATUS_HTTP_TIMEOUT_SECONDS", 5, 1, 15)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"upstream returned HTTP {response.status}")
        return json.loads(response.read(262_145).decode("utf-8"))


def _probe_url(url):
    if not url:
        return {"status": "not_configured"}
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return {"status": "unknown", "detail": "Некоректна HTTPS-адреса"}
        request = urllib.request.Request(url, method="GET", headers={"User-Agent": "UA-Dim-system-status/1"})
        timeout = _env_int("UA_HOMES_STATUS_HTTP_TIMEOUT_SECONDS", 5, 1, 15)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"status": "ok" if response.status < 400 else "degraded"}
    except (OSError, ValueError, urllib.error.URLError):
        return {"status": "down"}


def _safe_sentry_link(value):
    try:
        parsed = urllib.parse.urlsplit(str(value or ""))
    except ValueError:
        return None
    if parsed.scheme == "https" and parsed.hostname and (
        parsed.hostname == "sentry.io" or parsed.hostname.endswith(".sentry.io")
    ):
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return None


def _sentry_status():
    token = os.environ.get("UA_HOMES_SENTRY_API_TOKEN", "").strip()
    org = os.environ.get("SENTRY_ORG", "").strip()
    project = os.environ.get("SENTRY_BACKEND_PROJECT", "").strip()
    if not token or not org or not project:
        return {"status": "not_configured", "new_critical_count": None, "issues": []}
    if not _SLUG.fullmatch(org) or not _SLUG.fullmatch(project):
        return {"status": "unknown", "new_critical_count": None, "issues": []}
    query = urllib.parse.urlencode({
        "query": "is:unresolved firstSeen:-24h level:[error,fatal]",
        "statsPeriod": "24h",
        "limit": str(_MAX_ISSUES),
    })
    url = f"https://sentry.io/api/0/projects/{org}/{project}/issues/?{query}"
    try:
        rows = _request_json(url, headers={"Authorization": f"Bearer {token}"})
        issues = []
        for row in rows[:_MAX_ISSUES] if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            issues.append({
                "id": str(row.get("id", ""))[:80],
                "title": str(row.get("title") or "Без назви")[:200],
                "culprit": str(row.get("culprit") or "")[:200],
                "level": str(row.get("level") or "error")[:20],
                "count": int(row.get("count") or 0),
                "first_seen": row.get("firstSeen"),
                "last_seen": row.get("lastSeen"),
                "url": _safe_sentry_link(row.get("permalink")),
            })
        return {
            "status": "degraded" if issues else "ok",
            "new_critical_count": len(issues),
            "issues": issues,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
        return {"status": "unknown", "new_critical_count": None, "issues": []}


def _github_status():
    token = os.environ.get("UA_HOMES_GITHUB_TOKEN", "").strip()
    repository = os.environ.get("UA_HOMES_GITHUB_REPOSITORY", "Faraon1228/ua-homes").strip()
    workflow = os.environ.get("UA_HOMES_DEPLOY_WORKFLOW", "deploy.yml").strip()
    if not token:
        return {"status": "not_configured", "failed_runs": [], "latest_success_sha": None}
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not _SLUG.fullmatch(workflow):
        return {"status": "unknown", "failed_runs": [], "latest_success_sha": None}
    encoded_workflow = urllib.parse.quote(workflow, safe="")
    url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/{encoded_workflow}/runs"
        "?branch=main&event=push&per_page=20"
    )
    try:
        payload = _request_json(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
        failed = []
        latest_success_sha = None
        for run in runs:
            conclusion = run.get("conclusion")
            if conclusion == "success" and not latest_success_sha:
                latest_success_sha = str(run.get("head_sha") or "")[:40] or None
            if conclusion in {"failure", "cancelled", "timed_out", "action_required"} and len(failed) < _MAX_RUNS:
                failed.append({
                    "id": int(run.get("id") or 0),
                    "name": str(run.get("name") or "Deploy")[:120],
                    "conclusion": conclusion,
                    "sha": str(run.get("head_sha") or "")[:12],
                    "created_at": run.get("created_at"),
                    "url": str(run.get("html_url") or "") if str(run.get("html_url") or "").startswith(
                        f"https://github.com/{repository}/actions/runs/"
                    ) else None,
                })
        return {
            "status": "degraded" if failed else "ok",
            "failed_runs": failed,
            "latest_success_sha": latest_success_sha,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
        return {"status": "unknown", "failed_runs": [], "latest_success_sha": None}


def _ensure_snapshot_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS system_status_snapshot (
            snapshot_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            refreshed_at TEXT NOT NULL
        )
        """
    )


def _read_snapshot(db):
    _ensure_snapshot_table(db)
    row = db.execute(
        "SELECT payload_json, refreshed_at FROM system_status_snapshot WHERE snapshot_key = ?",
        ("production",),
    ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
        refreshed_at = dt.datetime.fromisoformat(str(row["refreshed_at"]).replace("Z", "+00:00"))
        return payload, refreshed_at
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_snapshot(db, payload, refreshed_at):
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    db.execute(
        """
        INSERT INTO system_status_snapshot (snapshot_key, payload_json, refreshed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(snapshot_key) DO UPDATE SET
            payload_json = excluded.payload_json,
            refreshed_at = excluded.refreshed_at
        """,
        ("production", encoded, _iso(refreshed_at)),
    )


def _notification_status():
    email = bool(os.environ.get("SENDGRID_API_KEY") or os.environ.get("SMTP_HOST"))
    telegram = bool(
        os.environ.get("UA_HOMES_TELEGRAM_BOT_TOKEN")
        and os.environ.get("UA_HOMES_TELEGRAM_CHAT_ID")
    )
    return {
        "status": "ok" if email and telegram else "degraded" if email or telegram else "not_configured",
        "email": "ok" if email else "not_configured",
        "telegram": "ok" if telegram else "not_configured",
    }


def _overall_status(services, sentry, deploys):
    values = [item["status"] for item in services.values()] + [sentry["status"], deploys["status"]]
    if "down" in values:
        return "down"
    if "degraded" in values:
        return "degraded"
    if "unknown" in values:
        return "unknown"
    return "ok"


def build_status(db):
    now = _utcnow()
    website = _probe_url(os.environ.get("UA_HOMES_PUBLIC_URL", "").rstrip("/") or None)
    services = {
        "website": website,
        "api": {"status": "ok"},
        "database": {"status": "ok"},
        "push": {
            "status": "ok" if (
                os.environ.get("UA_HOMES_FIREBASE_SERVICE_ACCOUNT_BASE64")
                or os.environ.get("UA_HOMES_ALERTS_PUSH_WEBHOOK_URL")
            ) else "not_configured"
        },
    }
    sentry = _sentry_status()
    deploys = _github_status()
    deployed_sha = (
        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT_SHA")
        or os.environ.get("SENTRY_RELEASE")
        or ""
    )[:40] or None
    expected_sha = deploys.get("latest_success_sha")
    version = {
        "release": os.environ.get("UA_HOMES_RELEASE_VERSION") or os.environ.get("SENTRY_RELEASE") or None,
        "sha": deployed_sha,
        "expected_sha": expected_sha,
        "mismatch": bool(deployed_sha and expected_sha and deployed_sha != expected_sha),
    }
    if version["mismatch"]:
        services["api"]["status"] = "degraded"
    payload = {
        "status": _overall_status(services, sentry, deploys),
        "database": services["database"]["status"],
        "services": services,
        "sentry": sentry,
        "deployments": deploys,
        "version": version,
        "notifications": _notification_status(),
        "refreshed_at": _iso(now),
        "stale": False,
    }
    return payload, now


def get_status(db, *, force=False):
    snapshot = _read_snapshot(db)
    ttl = _env_int("UA_HOMES_STATUS_TTL_SECONDS", _DEFAULT_TTL_SECONDS, 30, 3600)
    if snapshot and not force:
        payload, refreshed_at = snapshot
        age = (_utcnow() - refreshed_at).total_seconds()
        payload["stale"] = age > ttl
        return payload
    previous = snapshot[0] if snapshot else None
    payload, refreshed_at = build_status(db)
    _write_snapshot(db, payload, refreshed_at)
    db.commit()
    _notify_transition(previous, payload)
    return payload


def _notify_transition(previous, current):
    old_status = previous.get("status") if isinstance(previous, dict) else None
    new_status = current["status"]
    is_incident = new_status in {"degraded", "down"}
    recovered = old_status in {"degraded", "down"} and new_status == "ok"
    if (is_incident and old_status in {"degraded", "down"}) or (not is_incident and not recovered):
        return
    subject = (
        f"[UA-Dim] Система: {new_status}"
        if is_incident
        else "[UA-Dim] Система відновлена"
    )
    text = f"Стан: {new_status}\nОновлено: {current['refreshed_at']}"
    email = os.environ.get("UA_HOMES_STATUS_ALERT_EMAIL", "").strip()
    if email:
        from app import _send_email
        _send_email(email, subject, text, f"<p>{text.replace(chr(10), '<br>')}</p>")
    _send_telegram(subject, text)


def _send_telegram(subject, text):
    token = os.environ.get("UA_HOMES_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("UA_HOMES_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        return
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": f"{subject}\n{text}"}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
    )
    try:
        timeout = _env_int("UA_HOMES_STATUS_HTTP_TIMEOUT_SECONDS", 5, 1, 15)
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except (OSError, urllib.error.URLError):
        from flask import current_app
        current_app.logger.error("System status Telegram notification failed")


def scheduler_key_valid(supplied):
    expected = os.environ.get("UA_HOMES_STATUS_REFRESH_KEY", "")
    return bool(expected and supplied and hmac.compare_digest(str(supplied), expected))
