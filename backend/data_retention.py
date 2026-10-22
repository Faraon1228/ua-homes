"""Scheduled data-retention purge (runs inside the existing background-jobs runner).

Approved periods (all UTC, compared against ``created_at``):
  * ``lead_funnel_events`` and ``client_observability_events``: 30 days
  * ``lead_requests``: 12 calendar months from ``created_at`` (deleted, not anonymised)
  * ``listing_reports``: 12 calendar months after ``closed_at`` (resolved/dismissed only)

Rows strictly older than the cutoff are deleted in bounded batches with portable
SQL, so one run never holds a long transaction. Failures are logged without row
data and reported in the run summary instead of being swallowed.
``premium_orders`` and audit logs are intentionally not handled.
"""

from __future__ import annotations

import datetime
import logging

logger = logging.getLogger(__name__)

TELEMETRY_DAYS = 30
LEAD_MONTHS = 12
BATCH_SIZE = 500
MAX_BATCHES_PER_TABLE = 20

_STAMP = "%Y-%m-%d %H:%M:%S"


def months_before(moment: datetime.datetime, months: int) -> datetime.datetime:
    """Exact calendar-month subtraction; a missing day clamps to the month end."""
    index = moment.year * 12 + (moment.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    first_next = datetime.datetime(year + (month == 12), month % 12 + 1, 1)
    last_day = (first_next - datetime.timedelta(days=1)).day
    return moment.replace(year=year, month=month, day=min(moment.day, last_day))


def cutoffs(now: datetime.datetime) -> dict[str, str]:
    telemetry = (now - datetime.timedelta(days=TELEMETRY_DAYS)).strftime(_STAMP)
    leads = months_before(now, LEAD_MONTHS).strftime(_STAMP)
    return {
        "lead_funnel_events": telemetry,
        "client_observability_events": telemetry,
        "lead_requests": leads,
        "listing_reports": leads,
    }


# Reports age from their explicit close time (resolved/dismissed are final states); open and
# reviewing reports, and closed rows without a known close time, are never deleted.
_RULES = {
    "lead_requests": "created_at",
    "listing_reports": "closed_at",
}


def _purge_table(db, table: str, cutoff: str) -> int:
    column = _RULES.get(table, "created_at")
    extra = " AND status IN ('resolved', 'dismissed')" if table == "listing_reports" else ""
    deleted = 0
    for _ in range(MAX_BATCHES_PER_TABLE):
        cursor = db.execute(
            f"DELETE FROM {table} WHERE id IN ("
            f"SELECT id FROM {table} WHERE {column} IS NOT NULL AND {column} < ?{extra} ORDER BY id LIMIT ?)",
            (cutoff, BATCH_SIZE),
        )
        count = int(cursor.rowcount or 0)
        db.commit()
        deleted += count
        if count < BATCH_SIZE:
            break
    return deleted


def run_retention(db, app_mod=None, now: datetime.datetime | None = None) -> dict:
    now = now or datetime.datetime.utcnow()
    deleted: dict[str, int] = {}
    errors: list[str] = []
    for table, cutoff in cutoffs(now).items():
        try:
            deleted[table] = _purge_table(db, table, cutoff)
        except Exception:
            db.rollback()
            logger.exception("Retention purge failed for %s", table)
            errors.append(table)
    if app_mod is not None:
        if deleted.get("lead_funnel_events"):
            app_mod.cache_delete_prefix("admin:reports:lead-funnel:")
        if deleted.get("client_observability_events"):
            app_mod.cache_delete_prefix("admin:reports:observability:")
    return {"deleted": deleted, "errors": errors}
