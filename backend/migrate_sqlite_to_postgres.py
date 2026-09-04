#!/usr/bin/env python3
"""Copy a UA-Dim SQLite database into an empty PostgreSQL database."""

from __future__ import annotations

import argparse
import os
import secrets
import sqlite3
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values


TABLE_ORDER = [
    "users",
    "agency_profiles",
    "listings",
    "reviews",
    "listing_images",
    "moderation_log",
    "listing_alerts",
    "push_devices",
    "user_favorites",
    "alert_dispatch_runs",
    "system_status_snapshots",
    "system_incidents",
    "lead_funnel_events",
    "lead_funnel_daily_metrics",
    "lead_funnel_listing_metrics",
    "lead_funnel_session_rollups",
    "lead_requests",
    "client_observability_events",
    "listing_city_summary",
    "user_growth_daily",
    "premium_orders",
    "listing_reports",
    "listing_change_history",
    "admin_audit_log",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and optionally migrate UA-Dim SQLite data to PostgreSQL.",
    )
    parser.add_argument("--source", required=True, help="Path to the SQLite database")
    parser.add_argument(
        "--target",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL DSN (defaults to DATABASE_URL)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the copy. Without this flag, only validate both databases.",
    )
    return parser.parse_args()


def initialize_target(target_dsn: str) -> None:
    os.environ["DATABASE_URL"] = target_dsn
    os.environ["UA_HOMES_SEED_DEMO_DATA"] = "false"
    os.environ.pop("UA_HOMES_BOOTSTRAP_ADMIN_EMAIL", None)
    os.environ.pop("UA_HOMES_BOOTSTRAP_ADMIN_PASSWORD", None)
    os.environ.setdefault("UA_HOMES_SECRET", secrets.token_hex(32))

    import app as app_module

    if not app_module._is_postgres():
        raise RuntimeError("Target did not initialize as PostgreSQL")


def sqlite_columns(source: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in source.execute(f'PRAGMA table_info("{table}")')]


def postgres_columns(target, table: str) -> list[str]:
    with target.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [row[0] for row in cursor.fetchall()]


def row_count(connection, table: str, *, postgres: bool) -> int:
    query = sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table)) if postgres else f'SELECT COUNT(*) FROM "{table}"'
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        return int(cursor.fetchone()[0])
    finally:
        cursor.close()


def ensure_empty_target(target) -> None:
    occupied = {}
    for table in TABLE_ORDER:
        count = row_count(target, table, postgres=True)
        if count:
            occupied[table] = count
    if occupied:
        summary = ", ".join(f"{table}={count}" for table, count in occupied.items())
        raise RuntimeError(f"Target PostgreSQL database must be empty; found {summary}")


def preflight_target(target) -> None:
    with target.cursor() as cursor:
        cursor.execute(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema()
            """,
        )
        tables = {row[0] for row in cursor.fetchall()}
    unexpected = sorted(tables.difference(TABLE_ORDER))
    if unexpected:
        raise RuntimeError(
            "Target PostgreSQL schema must be dedicated to UA-Dim; found "
            + ", ".join(unexpected),
        )
    occupied = {}
    for table in sorted(tables):
        count = row_count(target, table, postgres=True)
        if count:
            occupied[table] = count
    if occupied:
        summary = ", ".join(f"{table}={count}" for table, count in occupied.items())
        raise RuntimeError(
            f"Target PostgreSQL database must be empty before schema initialization; found {summary}",
        )


def normalize_value(table: str, column: str, value):
    if table == "users" and column == "email" and isinstance(value, str):
        return value.strip().lower()
    return value


def migrate_table(source: sqlite3.Connection, target, table: str) -> int:
    source_columns = sqlite_columns(source, table)
    target_columns = set(postgres_columns(target, table))
    missing = [column for column in source_columns if column not in target_columns]
    if missing:
        raise RuntimeError(f"{table}: target is missing columns {', '.join(missing)}")

    statement = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, source_columns)),
    )
    source_cursor = source.execute(f'SELECT * FROM "{table}"')
    copied = 0
    while True:
        rows = source_cursor.fetchmany(500)
        if not rows:
            return copied
        values = [
            tuple(normalize_value(table, column, row[column]) for column in source_columns)
            for row in rows
        ]
        with target.cursor() as cursor:
            execute_values(cursor, statement.as_string(target), values, page_size=500)
        copied += len(rows)


def synchronize_identity(target, table: str) -> None:
    columns = postgres_columns(target, table)
    if "id" not in columns:
        return
    with target.cursor() as cursor:
        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
        sequence = cursor.fetchone()[0]
        if not sequence:
            return
        cursor.execute(
            sql.SQL("SELECT MAX(id) FROM {}").format(sql.Identifier(table)),
        )
        maximum = cursor.fetchone()[0]
        cursor.execute(
            "SELECT setval(%s::regclass, %s, %s)",
            (sequence, maximum or 1, maximum is not None),
        )


def main() -> int:
    args = parse_args()
    source_path = Path(args.source).expanduser().resolve()
    if not source_path.is_file():
        raise RuntimeError(f"SQLite source does not exist: {source_path}")
    if not args.target:
        raise RuntimeError("PostgreSQL target is required via --target or DATABASE_URL")
    if not args.target.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("Target must be a PostgreSQL DSN")

    preflight = psycopg2.connect(args.target)
    try:
        preflight_target(preflight)
    finally:
        preflight.close()

    initialize_target(args.target)
    source = sqlite3.connect(f"file:{source_path}?mode=ro&immutable=1", uri=True)
    source.row_factory = sqlite3.Row
    target = psycopg2.connect(args.target)
    try:
        source.execute("PRAGMA query_only=ON")
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")

        ensure_empty_target(target)
        source_tables = {
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            )
        }
        present_tables = [table for table in TABLE_ORDER if table in source_tables]
        missing_source = [table for table in TABLE_ORDER if table not in source_tables]
        counts = {
            table: row_count(source, table, postgres=False) if table in source_tables else 0
            for table in TABLE_ORDER
        }
        print("Validated empty PostgreSQL target and SQLite source:")
        for table, count in counts.items():
            print(f"  {table}: {count}")
        if missing_source:
            print(
                "  Newer target-only tables will remain empty: "
                + ", ".join(missing_source),
            )
        if not args.execute:
            print("Dry run complete. Re-run with --execute to copy data.")
            target.rollback()
            return 0

        copied = {}
        for table in present_tables:
            copied[table] = migrate_table(source, target, table)
            synchronize_identity(target, table)

        for table, expected in counts.items():
            actual = row_count(target, table, postgres=True)
            if actual != expected:
                raise RuntimeError(f"{table}: expected {expected} rows, copied {actual}")
        target.commit()
        print(f"Migration complete: {sum(copied.values())} rows copied and verified.")
        return 0
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()
        source.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        raise SystemExit(1)
