#!/usr/bin/env python3
"""Move legacy base64 listing photos from SQLite into Cloudinary."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import hashlib
import io
import json
import os
import re
import sqlite3
import sys

import cloudinary
import cloudinary.uploader

from app import (
    ALLOWED_IMAGE_TYPES,
    CLOUDINARY_URL,
    DATABASE_URL,
    DB_PATH,
    MAX_UPLOAD_SIZE,
)


DATA_IMAGE_RE = re.compile(
    r"^data:(?P<mime>image/[A-Za-z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/=\s]+)$"
)


def decode_legacy_image(value: str) -> tuple[bytes, str]:
    match = DATA_IMAGE_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("not a supported base64 image")
    mime_type = match.group("mime").lower()
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(f"unsupported image type: {mime_type}")
    try:
        image_bytes = base64.b64decode(match.group("payload"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 image") from exc
    if not image_bytes:
        raise ValueError("empty image")
    if len(image_bytes) > MAX_UPLOAD_SIZE:
        raise ValueError("image exceeds upload limit")
    return image_bytes, mime_type


def extension_for_mime(mime_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/avif": "avif",
        "image/heic": "heic",
        "image/heif": "heif",
        "image/gif": "gif",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
    }[mime_type]


def load_candidates(db: sqlite3.Connection, listing_ids: list[int]) -> list[sqlite3.Row]:
    db.row_factory = sqlite3.Row
    query = "SELECT id, user_id, title, images FROM listings WHERE images LIKE ?"
    params: list[object] = ["%data:image%"]
    if listing_ids:
        placeholders = ",".join("?" for _ in listing_ids)
        query += f" AND id IN ({placeholders})"
        params.extend(listing_ids)
    query += " ORDER BY id"
    return db.execute(query, params).fetchall()


def migrate(db: sqlite3.Connection, rows: list[sqlite3.Row], apply: bool) -> dict:
    stats = {
        "listings": len(rows),
        "legacy_images": 0,
        "migrated": 0,
        "failed": 0,
        "conflicts": 0,
    }
    for row in rows:
        images = json.loads(row["images"] or "[]")
        if not isinstance(images, list):
            stats["failed"] += 1
            continue
        updated_images = list(images)
        listing_changed = False
        listing_migrated = 0
        for index, value in enumerate(updated_images):
            if not isinstance(value, str) or not value.startswith("data:image/"):
                continue
            stats["legacy_images"] += 1
            try:
                image_bytes, mime_type = decode_legacy_image(value)
                if not apply:
                    continue
                digest = hashlib.sha256(image_bytes).hexdigest()[:16]
                public_id = f"listings/{row['user_id']}/legacy-{row['id']}-{index + 1}-{digest}"
                upload_file = io.BytesIO(image_bytes)
                upload_file.name = f"legacy-{row['id']}-{index + 1}.{extension_for_mime(mime_type)}"
                result = cloudinary.uploader.upload(
                    upload_file,
                    public_id=public_id,
                    resource_type="image",
                    overwrite=True,
                    unique_filename=False,
                )
                secure_url = str(result.get("secure_url") or "").strip()
                if not secure_url:
                    raise ValueError("Cloudinary did not return secure_url")
                updated_images[index] = secure_url
                listing_changed = True
                listing_migrated += 1
            except Exception as exc:
                stats["failed"] += 1
                print(f"listing={row['id']} image={index + 1} failed: {exc}", file=sys.stderr)
        if listing_changed:
            cursor = db.execute(
                """
                UPDATE listings
                SET images = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND images = ?
                """,
                (json.dumps(updated_images), row["id"], row["images"]),
            )
            if cursor.rowcount == 1:
                db.commit()
                stats["migrated"] += listing_migrated
            else:
                db.rollback()
                stats["conflicts"] += 1
                stats["failed"] += listing_migrated
                print(
                    f"listing={row['id']} skipped: images changed during migration",
                    file=sys.stderr,
                )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Upload and update records")
    parser.add_argument("--listing-id", action="append", type=int, default=[])
    args = parser.parse_args()

    if DATABASE_URL:
        print("This maintenance command only supports the SQLite deployment.", file=sys.stderr)
        return 2
    if args.apply and not CLOUDINARY_URL:
        print("CLOUDINARY_URL is required.", file=sys.stderr)
        return 2
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 2

    cloudinary.config(secure=True)
    with sqlite3.connect(DB_PATH) as db:
        rows = load_candidates(db, args.listing_id)
        if args.apply and rows:
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = f"{DB_PATH}.legacy-media-{timestamp}.bak"
            with sqlite3.connect(backup_path) as backup_db:
                db.backup(backup_db)
            print(f"backup={backup_path}")
        stats = migrate(db, rows, args.apply)

    print(json.dumps({"mode": "apply" if args.apply else "dry-run", **stats}, sort_keys=True))
    return 1 if stats["failed"] or stats["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
