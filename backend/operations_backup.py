from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path


REQUIRED_TABLES = ("users", "listings")


class BackupValidationError(RuntimeError):
    pass


def _read_only_connection(
    database_path: Path,
    *,
    immutable: bool = False,
) -> sqlite3.Connection:
    immutable_query = "&immutable=1" if immutable else ""
    return sqlite3.connect(
        f"file:{database_path}?mode=ro{immutable_query}",
        uri=True,
        timeout=30,
    )


def verify_database(database_path: str | os.PathLike[str]) -> dict:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise BackupValidationError(f"Database file does not exist: {path}")

    try:
        with _read_only_connection(path, immutable=True) as database:
            integrity_rows = [row[0] for row in database.execute("PRAGMA integrity_check").fetchall()]
            if integrity_rows != ["ok"]:
                raise BackupValidationError(f"SQLite integrity check failed: {integrity_rows}")

            table_names = {
                row[0]
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            missing_tables = [table for table in REQUIRED_TABLES if table not in table_names]
            if missing_tables:
                raise BackupValidationError(
                    f"Backup is missing required tables: {', '.join(missing_tables)}"
                )

            row_counts = {
                table: int(database.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                for table in REQUIRED_TABLES
            }
            user_version = int(database.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        raise BackupValidationError(f"Unable to read SQLite backup: {exc}") from exc

    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)

    return {
        "database": path.name,
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
        "integrity": "ok",
        "user_version": user_version,
        "row_counts": row_counts,
    }


def create_backup(
    source_path: str | os.PathLike[str],
    destination_path: str | os.PathLike[str],
    *,
    source_immutable: bool = False,
) -> dict:
    source = Path(source_path).resolve()
    destination = Path(destination_path).resolve()
    if not source.is_file():
        raise BackupValidationError(f"Source database does not exist: {source}")
    if source == destination:
        raise BackupValidationError("Backup destination must differ from the source database")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(temporary_fd)
    temporary_path = Path(temporary_name)

    try:
        with _read_only_connection(source, immutable=source_immutable) as source_database:
            with sqlite3.connect(temporary_path, timeout=30) as backup_database:
                source_database.backup(backup_database)
        summary = verify_database(temporary_path)
        os.replace(temporary_path, destination)
        summary["database"] = destination.name
        return summary
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def restore_drill(database_path: str | os.PathLike[str]) -> dict:
    source = Path(database_path).resolve()
    with tempfile.TemporaryDirectory(prefix="ua-homes-restore-") as temporary_directory:
        restored_path = Path(temporary_directory) / "restored.sqlite3"
        summary = create_backup(source, restored_path, source_immutable=True)
        summary["restore_drill"] = "ok"
        return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and validate UA Homes SQLite backups")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a consistent SQLite backup")
    create_parser.add_argument(
        "--source",
        default=os.environ.get("UA_HOMES_DB_PATH", ""),
        help="Source SQLite path (defaults to UA_HOMES_DB_PATH)",
    )
    create_parser.add_argument("--output", required=True, help="Backup output path")

    verify_parser = subparsers.add_parser("verify", help="Run SQLite integrity checks")
    verify_parser.add_argument("--database", required=True, help="Backup path")

    drill_parser = subparsers.add_parser(
        "restore-drill",
        help="Restore into a temporary database and validate required tables",
    )
    drill_parser.add_argument("--database", required=True, help="Backup path")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "create":
        if not args.source:
            raise SystemExit("--source or UA_HOMES_DB_PATH is required")
        summary = create_backup(args.source, args.output)
    elif args.command == "verify":
        summary = verify_database(args.database)
    else:
        summary = restore_drill(args.database)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
