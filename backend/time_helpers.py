from __future__ import annotations

import datetime


UTC = datetime.timezone.utc


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(UTC)


def legacy_utc_now() -> datetime.datetime:
    """Return aware UTC time in the naive shape used by existing DB values."""
    return utc_now().replace(tzinfo=None)


def legacy_timestamp(
    value: datetime.datetime | None = None,
    *,
    timespec: str = "auto",
) -> str:
    current = legacy_utc_now() if value is None else value
    if current.tzinfo is not None:
        current = current.astimezone(UTC).replace(tzinfo=None)
    return current.isoformat(sep=" ", timespec=timespec)
