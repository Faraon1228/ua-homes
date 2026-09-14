"""
UA-Dim Listings, Favorites, Alerts & Leads Routes
Modularized blueprint for listing CRUD, favorites, saved-search alerts,
push devices, recommendations, map search, leads/inquiries, and the
related client-facing analytics endpoints.
"""

import base64
import datetime
import hashlib
import json
import re
import secrets
from html import escape
from urllib.parse import urlsplit

from flask import Response, Blueprint, g, jsonify, request

try:
    from app import limiter, _request_has_active_actor
except ImportError:
    from backend.app import limiter, _request_has_active_actor

listing_bp = Blueprint("listing_bp", __name__)


def _get_app_module():
    """Dynamically get the main app module to access shared globals and helpers."""
    import sys
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


def require_auth(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        app_mod = _get_app_module()
        return app_mod.require_auth(f)(*args, **kwargs)
    return decorated



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


def _listing_search_filter(db, search: str) -> tuple[str, list, list[int]]:
    from app import _is_postgres
    token = f"%{search}%"
    like_clause = " AND (l.title LIKE ? OR l.city LIKE ? OR l.district LIKE ? OR l.description LIKE ?)"
    if _is_postgres():
        return like_clause, [token, token, token, token], []

    try:
        fts_rows = db.execute(
            "SELECT rowid FROM listings_fts WHERE listings_fts MATCH ? ORDER BY rank LIMIT 500",
            (search,),
        ).fetchall()
        fts_ids = [int(row[0]) for row in fts_rows if int(row[0]) > 0]
        if not fts_ids:
            return " AND 1=0", [], []
        placeholders = ",".join("?" for _ in fts_ids)
        return f" AND l.id IN ({placeholders})", fts_ids, fts_ids[:200]
    except Exception:
        return like_clause, [token, token, token, token], []


LISTING_SELECT = """
    SELECT l.id, l.user_id, l.title, l.region, l.city, l.district, l.property_type, l.condition_type,
           l.price, l.rooms, l.area, l.floor, l.total_floors, l.year_built,
           l.e_oselya, l.views, l.images, l.videos, l.latitude, l.longitude, l.description,
           l.status, l.listing_type, l.source, l.agency_slug, l.listing_status, l.has_photo_tour, l.has_video_tour,
           l.verified_owner, l.verified_phone, l.verified_docs,
           l.owner_verification_status, l.phone_verification_status,
           l.moderation_status, l.moderation_reason, l.moderation_updated_at,
           l.listing_verification_status,
           l.last_confirmed_at, l.freshness_reminder_sent_at,
           l.published_at, l.created_at,
           COALESCE(dup.dup_count, 1) AS dup_count,
           u.name AS owner_name, u.email AS owner_email, u.phone AS owner_phone,
           u.phone_verified AS owner_phone_verified, u.account_type AS owner_account_type,
           u.agency_slug AS owner_agency_slug,
           ap.name AS agency_name, ap.kind AS agency_kind, ap.is_verified AS agency_verified
    FROM   listings l
    JOIN   users u ON u.id = l.user_id
    LEFT JOIN agency_profiles ap ON ap.slug = u.agency_slug AND ap.status = 'active'
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


@limiter.limit("600 per hour")  # 10 requests/min average, burst 30/min
@listing_bp.route("/api/listings", methods=["GET"])
def get_listings():
    from app import (
        REGION_SETTLEMENTS_MAP,
        UKRAINIAN_REGIONS,
        _row_to_listing,
        cached_json_get,
        cached_json_set,
        get_db,
        get_optional_actor,
        nonneg_int,
        normalize_region_name,
        pos_float,
        pos_int,
        strip,
        truthy_flag,
    )
    db   = get_db()
    args = request.args

    mine_only     = truthy_flag(args.get("mine"))
    region        = strip(args.get("region",    ""), 100)
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

    if region and region != "Всі":
        norm_region = normalize_region_name(region)
        region_cities = REGION_SETTLEMENTS_MAP.get(norm_region, [])
        if region_cities:
            placeholders = ",".join("?" for _ in region_cities)
            query += f" AND (l.region = ? OR (COALESCE(l.region, '') = '' AND l.city IN ({placeholders})))"
            params.extend([norm_region, *region_cities])
        else:
            query += " AND l.region = ?"
            params.append(norm_region)

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
        search_clause, search_params, ranked_fts_ids = _listing_search_filter(db, search)
        query += search_clause
        params.extend(search_params)
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
        region_rows = db.execute(
            """
            SELECT DISTINCT region
            FROM listings
            WHERE status = 'published' AND TRIM(COALESCE(region, '')) <> ''
            ORDER BY region
            """
        ).fetchall()
        db_regions = [row[0] for row in region_rows if row[0]]
        all_regions = list(dict.fromkeys([*UKRAINIAN_REGIONS, *db_regions]))
        response_payload["facets"] = {
            "regions": all_regions,
            "cities": [row[0] for row in city_rows],
        }
    if cache_key and cacheable_public_query:
        cached_json_set(cache_key, response_payload, ttl_seconds=20)
    return jsonify(**response_payload)


@limiter.limit("1200 per hour")  # 20 requests/min average
@listing_bp.route("/api/listings/<int:lid>", methods=["GET"])
def get_listing(lid: int):
    from app import (
        _row_to_listing,
        get_db,
        get_optional_actor,
    )
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


@listing_bp.route("/api/listings/<int:lid>/view", methods=["POST"])
@limiter.limit("60 per minute")
def increment_view(lid: int):
    from app import get_db
    db = get_db()
    db.execute("UPDATE listings SET views = views + 1 WHERE id = ?", (lid,))
    db.commit()
    row = db.execute("SELECT views FROM listings WHERE id = ?", (lid,)).fetchone()
    return jsonify(views=row["views"] if row else 0)


@listing_bp.route("/api/listings/<int:lid>/reviews", methods=["GET"])
def get_reviews(lid: int):
    from app import get_db
    db = get_db()
    rows = db.execute(
        "SELECT id, user_name, rating, comment, created_at FROM reviews WHERE listing_id = ? ORDER BY created_at DESC",
        (lid,)
    ).fetchall()
    return jsonify(reviews=[dict(r) for r in rows])


@listing_bp.route("/api/listings/<int:lid>/reviews", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def add_review(lid: int):
    from app import (
        get_db,
        nonneg_int,
        strip,
    )
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


@listing_bp.route("/api/listings/<int:lid>/trust", methods=["GET"])
def get_listing_trust(lid: int):
    """Public trust surface for a listing: real listing-verification status
    (distinct from moderation/owner verification), the seller type derived
    from the account itself, comparable-price statistics, and sanitized
    field history. Never exposes reporter data, moderation notes, owner
    email, or admin identifiers."""
    from app import (
        _row_to_listing,
        comparable_price_stats,
        get_db,
        get_optional_actor,
        public_field_history,
    )
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


@listing_bp.route("/api/listings/<int:lid>/reports", methods=["POST"])
@limiter.limit("5 per hour")
def report_listing(lid: int):
    """File a fraud/quality report against a published listing. Works for
    authenticated users (via bearer token) and anonymous visitors (via a
    client-generated reporter_session_id). Reporter identity is never stored
    directly — only a non-reversible HMAC fingerprint used for dedupe."""
    from app import (
        REPORT_REASON_CODES,
        _is_db_integrity_error,
        _reporter_fingerprint,
        db_now_expr,
        db_timestamp_column_expr,
        get_db,
        get_optional_actor,
        strip,
    )
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

    created_at_expression = db_timestamp_column_expr("created_at")
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
        LEFT JOIN agency_profiles ap ON ap.slug = u.agency_slug AND ap.status = 'active'
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


@listing_bp.route("/api/listings", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def create_listing():
    from app import (
        _refresh_listing_city_summary,
        _row_to_listing,
        cache_delete_prefix,
        get_db,
        listing_usage,
        log_listing_event,
        normalize_account_type,
        parse_listing_request_payload,
        plan_public_dict,
        resolve_user_plan,
        run_dispatch_with_logging,
        truthy_flag,
        validate_listing_payload,
    )
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
            (user_id,title,region,city,district,property_type,condition_type,price,rooms,area,
            floor,total_floors,year_built,e_oselya,images,videos,latitude,longitude,description,
            status,published_at,listing_type,source,agency_slug,listing_status,has_photo_tour,has_video_tour,
            verified_owner,verified_phone,verified_docs,
            owner_verification_status,phone_verification_status,
            moderation_status,moderation_reason,moderation_updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (g.user_id, listing_payload["title"], listing_payload["region"], listing_payload["city"], listing_payload["district"], listing_payload["property_type"], listing_payload["condition_type"], listing_payload["price"], listing_payload["rooms"], listing_payload["area"],
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


@listing_bp.route("/api/listings/<int:listing_id>", methods=["PATCH"])
@require_auth
@limiter.limit("60 per hour")
def update_listing(listing_id: int):
    from app import (
        _infer_region_from_city,
        _refresh_listing_city_summary,
        _row_to_listing,
        cache_delete_prefix,
        cleanup_listing_media,
        db_text_timestamp_expr,
        get_db,
        has_legacy_data_uri_images,
        log_field_change,
        log_listing_event,
        normalize_account_type,
        parse_listing_request_payload,
        run_dispatch_with_logging,
        truthy_flag,
        validate_listing_payload,
        verification_state_from_bool,
    )
    db = get_db()
    text_now_expr = db_text_timestamp_expr()
    listing = db.execute(
        """
        SELECT id, user_id, status, published_at, moderation_status, moderation_reason,
               verified_owner, verified_phone, verified_docs,
               owner_verification_status, phone_verification_status,
               listing_verification_status,
               title, region, city, district, property_type, condition_type, price, rooms, area,
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
        "region": listing_payload["region"],
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
    def _existing_field_val(field_name):
        if field_name == "region":
            return listing["region"] or _infer_region_from_city(listing["city"]) or ""
        return listing[field_name]

    substantive_changed = any(_existing_field_val(field) != value for field, value in substantive_fields.items())
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
            region = ?,
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
            published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, {text_now_expr}) ELSE published_at END,
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
            moderation_updated_at = {text_now_expr},
            listing_verification_status = ?
        WHERE id = ?
        """,
        (
            listing_payload["title"],
            listing_payload["region"],
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
    elif (
        next_status == "published"
        and int(listing["price"] or 0) != int(listing_payload["price"] or 0)
    ):
        run_dispatch_with_logging(
            db,
            trigger_type="listing_price_change",
            listing_id=listing_id,
            dry_run=False,
            raise_errors=False,
            event_type="price_change",
            previous_price=int(listing["price"] or 0),
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


@listing_bp.route("/api/listings/<int:listing_id>/confirm-active", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def confirm_listing_active(listing_id: int):
    from app import (
        cache_delete_prefix,
        get_db,
        log_listing_event,
    )
    db = get_db()
    listing = db.execute(
        "SELECT id, user_id, status, listing_status FROM listings WHERE id = ?",
        (listing_id,),
    ).fetchone()
    if not listing:
        return jsonify(error="Оголошення не знайдено"), 404
    if listing["user_id"] != g.user_id:
        return jsonify(error="Недостатньо прав"), 403
    if listing["status"] != "published" or listing["listing_status"] != "active":
        return jsonify(error="Підтвердити можна лише активне опубліковане оголошення"), 409

    confirmed_at = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    db.execute(
        """
        UPDATE listings
        SET last_confirmed_at = ?, freshness_reminder_sent_at = NULL
        WHERE id = ?
        """,
        (confirmed_at, listing_id),
    )
    log_listing_event(db, listing_id, "listing_freshness_confirmed", "Продавець підтвердив актуальність оголошення.")
    db.commit()
    cache_delete_prefix("public:listings:")
    return jsonify(ok=True, last_confirmed_at=confirmed_at, needs_freshness_confirmation=False)


@listing_bp.route("/api/listings/freshness/remind", methods=["POST"])
def remind_stale_listings():
    from app import (
        PUBLIC_SITE_URL,
        _send_email,
        alerts_dispatch_authorized,
        get_db,
        public_seller_url,
    )
    db = get_db()
    allowed, trigger_auth = alerts_dispatch_authorized(db)
    if not allowed:
        return jsonify(error="Недостатньо прав для нагадувань"), 403

    now = datetime.datetime.utcnow().replace(microsecond=0)
    stale_before = (now - datetime.timedelta(days=30)).isoformat(sep=" ")
    reminder_before = (now - datetime.timedelta(days=7)).isoformat(sep=" ")
    rows = db.execute(
        """
        SELECT l.id, l.title, u.email, u.name
        FROM listings l
        JOIN users u ON u.id = l.user_id
        WHERE l.status = 'published'
          AND l.listing_status = 'active'
          AND COALESCE(l.last_confirmed_at, l.published_at, l.created_at) <= ?
          AND (
            l.freshness_reminder_sent_at IS NULL
            OR l.freshness_reminder_sent_at <= ?
          )
        ORDER BY COALESCE(l.last_confirmed_at, l.published_at, l.created_at) ASC
        LIMIT 250
        """,
        (stale_before, reminder_before),
    ).fetchall()

    sent = 0
    for row in rows:
        listing_url = f"{PUBLIC_SITE_URL or 'http://localhost:8080'}/listing/{row['id']}"
        confirmed = _send_email(
            row["email"],
            f"Підтвердіть актуальність оголошення №{row['id']} — UA-Dim",
            (
                f"{row['name'] or 'Вітаємо'}, підтвердіть, що оголошення «{row['title']}» ще актуальне.\n"
                f"Відкрийте кабінет продавця: {public_seller_url()}"
            ),
            (
                f"<p>{escape(row['name'] or 'Вітаємо')}, підтвердіть, що оголошення "
                f"<a href=\"{listing_url}\">«{escape(row['title'])}»</a> ще актуальне.</p>"
                f"<p><a href=\"{public_seller_url()}\">Відкрити кабінет продавця</a></p>"
            ),
        )
        if confirmed:
            db.execute(
                "UPDATE listings SET freshness_reminder_sent_at = ? WHERE id = ?",
                (now.isoformat(sep=" "), row["id"]),
            )
            sent += 1
    db.commit()
    return jsonify(ok=True, trigger_auth=trigger_auth, checked=len(rows), sent=sent)


@listing_bp.route("/api/admin/test-listings/cleanup", methods=["POST"])
@require_auth
@limiter.limit("10 per hour")
def cleanup_test_listings():
    from app import (
        _refresh_listing_city_summary,
        cache_delete_prefix,
        get_db,
        log_admin_audit,
        log_listing_event,
    )
    db = get_db()
    actor = db.execute("SELECT role FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not actor or actor["role"] != "admin":
        return jsonify(error="Недостатньо прав"), 403
    data = _parse_json_payload()
    apply_cleanup = bool(data.get("apply"))
    candidates = db.execute(
        """
        SELECT l.id, l.title, l.status, l.source, u.email AS owner_email
        FROM listings l
        JOIN users u ON u.id = l.user_id
        WHERE l.status IN ('published', 'pending', 'draft')
          AND (
            l.source = 'seed'
            OR l.title LIKE 'Тестове оголошення%'
            OR l.title LIKE 'тестове оголошення%'
            OR LOWER(u.email) = 'demo@ua-dim.com'
          )
        ORDER BY l.id
        LIMIT 500
        """
    ).fetchall()
    candidate_list = [dict(row) for row in candidates]
    if apply_cleanup and candidate_list:
        ids = [row["id"] for row in candidate_list]
        placeholders = ",".join("?" for _ in ids)
        db.execute(
            f"""
            UPDATE listings
            SET status = 'archived', listing_status = 'removed'
            WHERE id IN ({placeholders})
            """,
            tuple(ids),
        )
        for listing_id in ids:
            log_listing_event(
                db,
                listing_id,
                "test_listing_archived",
                "Тестове оголошення прибрано з публічного каталогу.",
                admin_id=g.user_id,
            )
        log_admin_audit(
            db,
            actor_id=g.user_id,
            actor_role="admin",
            action="post:test_listing_cleanup",
            permission="admin/all",
            resource_type="listings",
            resource_id="bulk",
            changed_fields=("status", "listing_status"),
        )
        _refresh_listing_city_summary(db)
        db.commit()
        cache_delete_prefix("public:listings:")
    return jsonify(
        ok=True,
        dry_run=not apply_cleanup,
        candidate_count=len(candidate_list),
        archived_count=len(candidate_list) if apply_cleanup else 0,
        candidates=candidate_list,
    )


@listing_bp.route("/api/listings/<int:listing_id>", methods=["DELETE"])
@require_auth
@limiter.limit("20 per hour")
def delete_listing(listing_id: int):
    from app import (
        _refresh_listing_city_summary,
        cache_delete_prefix,
        cleanup_listing_media,
        get_db,
    )
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


@listing_bp.route("/api/listings/<int:listing_id>/verification", methods=["PATCH"])
@require_auth
def update_listing_verification(listing_id: int):
    from app import (
        MODERATION_STATES,
        VERIFICATION_STATES,
        _refresh_listing_city_summary,
        _row_to_listing,
        cache_delete_prefix,
        db_text_timestamp_expr,
        get_db,
        log_admin_audit,
        log_field_change,
        log_listing_event,
        moderation_state_from_status,
        run_dispatch_with_logging,
        strip,
        verification_state_from_bool,
    )
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
            published_at_sql = f"COALESCE(published_at, {db_text_timestamp_expr()})"
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
            moderation_updated_at = {db_text_timestamp_expr()},
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
        log_admin_audit(
            db,
            actor_id=g.user_id,
            actor_role="admin",
            action="patch:listing_verification",
            permission="verifications/manage",
            resource_type="listing",
            resource_id=listing_id,
            changed_fields=data.keys(),
        )
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


@listing_bp.route("/api/favorites", methods=["GET"])
@require_auth
def list_user_favorites():
    from app import get_db
    db = get_db()
    rows = db.execute(
        """
        SELECT uf.listing_id
        FROM user_favorites uf
        JOIN listings l ON l.id = uf.listing_id
        WHERE uf.user_id = ? AND l.status = 'published'
        ORDER BY uf.created_at DESC
        """,
        (g.user_id,),
    ).fetchall()
    return jsonify(listing_ids=[row["listing_id"] for row in rows])


@listing_bp.route("/api/favorites/<int:listing_id>", methods=["PUT", "DELETE"])
@require_auth
@limiter.limit("120 per minute")
def update_user_favorite(listing_id: int):
    from app import get_db
    db = get_db()
    if request.method == "DELETE":
        db.execute(
            "DELETE FROM user_favorites WHERE user_id = ? AND listing_id = ?",
            (g.user_id, listing_id),
        )
        db.commit()
        return jsonify(ok=True, favorite=False)

    listing = db.execute(
        "SELECT id FROM listings WHERE id = ? AND status = 'published'",
        (listing_id,),
    ).fetchone()
    if not listing:
        return jsonify(error="Оголошення не знайдено"), 404
    db.execute(
        """
        INSERT INTO user_favorites (user_id, listing_id)
        VALUES (?, ?)
        ON CONFLICT (user_id, listing_id) DO NOTHING
        """,
        (g.user_id, listing_id),
    )
    db.commit()
    return jsonify(ok=True, favorite=True)


@listing_bp.route("/api/favorites/sync", methods=["POST"])
@require_auth
@limiter.limit("20 per minute")
def sync_user_favorites():
    from app import (
        get_db,
        nonneg_int,
    )
    db = get_db()
    data = _parse_json_payload()
    raw_ids = data.get("listing_ids")
    if not isinstance(raw_ids, list):
        return jsonify(error="listing_ids must be an array"), 422
    listing_ids = []
    for raw_id in raw_ids[:250]:
        listing_id = nonneg_int(raw_id)
        if listing_id and listing_id not in listing_ids:
            listing_ids.append(listing_id)

    if listing_ids:
        placeholders = ",".join("?" for _ in listing_ids)
        valid_rows = db.execute(
            f"SELECT id FROM listings WHERE status = 'published' AND id IN ({placeholders})",
            tuple(listing_ids),
        ).fetchall()
        for row in valid_rows:
            db.execute(
                """
                INSERT INTO user_favorites (user_id, listing_id)
                VALUES (?, ?)
                ON CONFLICT (user_id, listing_id) DO NOTHING
                """,
                (g.user_id, row["id"]),
            )
    rows = db.execute(
        """
        SELECT uf.listing_id
        FROM user_favorites uf
        JOIN listings l ON l.id = uf.listing_id
        WHERE uf.user_id = ? AND l.status = 'published'
        ORDER BY uf.created_at DESC
        """,
        (g.user_id,),
    ).fetchall()
    db.commit()
    return jsonify(ok=True, listing_ids=[row["listing_id"] for row in rows])


def _serialize_listing_alert(row) -> dict:
    try:
        filters = json.loads(row["filters"] or "{}")
    except (TypeError, ValueError):
        filters = {}
    if not isinstance(filters, dict):
        filters = {}
    return {
        "id": row["id"],
        "name": row["name"] or "Збережений пошук",
        "filters": filters,
        "is_active": bool(row["is_active"]),
        "last_sent_at": row["last_sent_at"],
        "created_at": row["created_at"],
    }


@listing_bp.route("/api/alerts", methods=["GET"])
@require_auth
def list_listing_alerts():
    from app import get_db
    db = get_db()
    rows = db.execute(
        """
        SELECT id, name, filters, is_active, last_sent_at, created_at
        FROM listing_alerts
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (g.user_id,),
    ).fetchall()
    return jsonify(alerts=[_serialize_listing_alert(row) for row in rows])


@listing_bp.route("/api/push/devices", methods=["POST", "DELETE"])
@require_auth
@limiter.limit("30 per minute")
def update_push_device():
    from app import (
        get_db,
        strip,
    )
    db = get_db()
    data = request.get_json(silent=True) or {}
    token = strip(data.get("token"), 4096)
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    if not token:
        return jsonify(error="Push-токен обов'язковий"), 400

    if request.method == "DELETE":
        db.execute(
            "UPDATE push_devices SET is_active = 0, last_seen_at = ? WHERE token = ? AND user_id = ?",
            (now, token, g.user_id),
        )
        db.commit()
        return jsonify(ok=True)

    platform = strip(data.get("platform"), 20).lower()
    if platform not in {"android", "ios"}:
        return jsonify(error="Непідтримувана мобільна платформа"), 400

    db.execute(
        """
        INSERT INTO push_devices (user_id, token, platform, is_active, last_seen_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(token) DO UPDATE SET
            user_id = excluded.user_id,
            platform = excluded.platform,
            is_active = 1,
            last_seen_at = excluded.last_seen_at
        """,
        (g.user_id, token, platform, now),
    )
    db.commit()
    return jsonify(ok=True)


@listing_bp.route("/api/alerts/<int:alert_id>", methods=["PATCH", "DELETE"])
@require_auth
@limiter.limit("60 per minute")
def update_listing_alert(alert_id: int):
    from app import get_db
    db = get_db()
    row = db.execute(
        "SELECT id FROM listing_alerts WHERE id = ? AND user_id = ?",
        (alert_id, g.user_id),
    ).fetchone()
    if not row:
        return jsonify(error="Збережений пошук не знайдено"), 404
    if request.method == "DELETE":
        db.execute("DELETE FROM listing_alerts WHERE id = ?", (alert_id,))
        db.commit()
        return jsonify(ok=True)

    data = _parse_json_payload()
    if "is_active" not in data:
        return jsonify(error="is_active is required"), 422
    requested_active = bool(data["is_active"])
    if requested_active:
        activation_allowed = db.execute(
            """
            SELECT 1
            FROM listing_alerts AS la
            JOIN users AS u ON u.id = la.user_id
            WHERE la.id = ? AND la.user_id = ?
              AND (la.verified_at IS NOT NULL OR u.email_verified = 1)
            """,
            (alert_id, g.user_id),
        ).fetchone()
        if not activation_allowed:
            return jsonify(error="Підтвердіть email перед активацією сповіщення"), 409
    db.execute(
        "UPDATE listing_alerts SET is_active = ? WHERE id = ?",
        (int(requested_active), alert_id),
    )
    db.commit()
    return jsonify(ok=True, is_active=requested_active)


@listing_bp.route("/api/alerts", methods=["POST"])
@limiter.limit(
    "5 per hour; 2 per minute",
    exempt_when=_request_has_active_actor,
)
def create_listing_alert():
    from app import (
        ALERT_ANONYMOUS_EMAIL_CAP,
        ALERT_USER_CAP,
        ALERT_VERIFY_COOLDOWN_MINUTES,
        ALERT_VERIFY_TTL_HOURS,
        _is_postgres,
        _token_hash,
        get_db,
        get_optional_actor,
        nonneg_int,
        normalize_alert_email,
        pos_int,
        send_alert_verification_email,
        strip,
        validate_email,
    )
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
    min_area = nonneg_int(data.get("minArea"))
    max_area = nonneg_int(data.get("maxArea"))
    keyword = strip(data.get("keywordSearch"), 120)
    sort_by = strip(data.get("sortBy"), 30)
    e_oselya = bool(data.get("eOselya"))
    listing_type = strip(data.get("listingType"), 10).lower()
    requested_channels = data.get("channels")
    email_channel = data.get("email")
    push_channel = data.get("push")

    user_id, _ = get_optional_actor(db)
    email = normalize_alert_email(data.get("email"))
    if user_id:
        row = db.execute(
            "SELECT email, email_verified FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        email = normalize_alert_email(row["email"]) if row else email
        account_email_verified = bool(row and row["email_verified"])
    else:
        account_email_verified = False

    if not email or not validate_email(email):
        return jsonify(error="Потрібен валідний email для алерта"), 422

    channels: list[str] = []
    if isinstance(requested_channels, list):
        channels = [strip(channel, 20).lower() for channel in requested_channels]
        channels = [channel for channel in channels if channel in {"email", "push"}]
    else:
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
        "minArea": min_area,
        "maxArea": max_area,
        "keywordSearch": keyword or None,
        "sortBy": sort_by or "newest",
        "eOselya": e_oselya,
        "channels": channels,
    }
    serialized_filters = json.dumps(filters, ensure_ascii=False, sort_keys=True)
    scope = f"user:{user_id}" if user_id else f"email:{email}"
    subscription_key = hashlib.sha256(
        f"{scope}\n{serialized_filters}".encode("utf-8")
    ).hexdigest()
    now = datetime.datetime.utcnow().replace(microsecond=0)
    now_text = now.isoformat(sep=" ")
    if _is_postgres():
        db.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (scope,))
    else:
        db.execute("BEGIN IMMEDIATE")
    db.execute(
        """
        UPDATE listing_alerts
        SET verification_token_hash = NULL, verification_expires_at = NULL
        WHERE email_normalized = ? AND is_active = 0
          AND verification_expires_at IS NOT NULL
          AND verification_expires_at <= ?
        """,
        (email, now_text),
    )

    existing = db.execute(
        """
        SELECT id, is_active, verification_token_hash, verification_expires_at,
               verification_sent_at
        FROM listing_alerts WHERE subscription_key = ?
        """,
        (subscription_key,),
    ).fetchone()
    if existing and (existing["is_active"] or account_email_verified):
        if user_id:
            db.execute(
                "UPDATE listing_alerts SET is_active = 1, verification_token_hash = NULL,"
                " verification_expires_at = NULL, verified_at = COALESCE(verified_at, ?)"
                " WHERE id = ?",
                (now_text, existing["id"]),
            )
        db.commit()
        if user_id:
            return jsonify(ok=True, id=existing["id"], duplicate=True), 200
        return jsonify(ok=True, status="pending"), 202

    count_query = (
        "SELECT COUNT(*) AS total FROM listing_alerts WHERE user_id = ?"
        if user_id
        else "SELECT COUNT(*) AS total FROM listing_alerts WHERE email_normalized = ?"
    )
    count_value = user_id if user_id else email
    count = int(db.execute(
        count_query + " AND (is_active = 1 OR verification_token_hash IS NOT NULL)",
        (count_value,),
    ).fetchone()["total"])
    cap = ALERT_USER_CAP if user_id else ALERT_ANONYMOUS_EMAIL_CAP
    if count >= cap and not existing:
        db.commit()
        if user_id:
            return jsonify(error="Досягнуто ліміт збережених пошуків"), 409
        return jsonify(ok=True, status="pending"), 202

    is_active = int(bool(user_id and account_email_verified))
    raw_verification_token = None
    token_hash = None
    verification_expires = None
    should_send_verification = False
    if not is_active:
        sent_at = existing["verification_sent_at"] if existing else None
        cooldown_before = (now - datetime.timedelta(minutes=ALERT_VERIFY_COOLDOWN_MINUTES)).isoformat(sep=" ")
        should_send_verification = not sent_at or sent_at <= cooldown_before
        if should_send_verification:
            raw_verification_token = secrets.token_urlsafe(32)
            token_hash = _token_hash(raw_verification_token)
            verification_expires = (
                now + datetime.timedelta(hours=ALERT_VERIFY_TTL_HOURS)
            ).isoformat(sep=" ")

    db.execute(
        """
        INSERT INTO listing_alerts (
            user_id, email, email_normalized, name, filters, is_active,
            subscription_key, verification_token_hash, verification_expires_at,
            verification_sent_at, verified_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(subscription_key) DO UPDATE SET
            name = excluded.name,
            verification_token_hash = COALESCE(excluded.verification_token_hash, listing_alerts.verification_token_hash),
            verification_expires_at = COALESCE(excluded.verification_expires_at, listing_alerts.verification_expires_at),
            verification_sent_at = COALESCE(excluded.verification_sent_at, listing_alerts.verification_sent_at)
        """,
        (
            user_id, email, email, name or "Listing alert", serialized_filters,
            is_active, subscription_key, token_hash, verification_expires,
            now_text if should_send_verification else None,
            now_text if is_active else None,
        ),
    )
    db.commit()
    created = db.execute(
        "SELECT id FROM listing_alerts WHERE subscription_key = ?", (subscription_key,)
    ).fetchone()
    if should_send_verification and raw_verification_token:
        send_alert_verification_email(email, raw_verification_token)
    if user_id and is_active:
        return jsonify(ok=True, id=created["id"], duplicate=False), 201
    return jsonify(ok=True, status="pending"), 202


@listing_bp.route("/api/alerts/verify", methods=["GET"])
@limiter.limit("20 per hour")
def verify_listing_alert():
    from app import (
        _token_hash,
        get_db,
        strip,
    )
    token = strip(request.args.get("token"), 500)
    token_hash = _token_hash(token) if token else ""
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    db = get_db()
    cursor = db.execute(
        """
        UPDATE listing_alerts
        SET is_active = 1, verified_at = ?, verification_token_hash = NULL,
            verification_expires_at = NULL
        WHERE verification_token_hash = ? AND is_active = 0
          AND verification_expires_at > ?
        """,
        (now, token_hash, now),
    )
    activated = cursor.rowcount == 1
    db.commit()
    message = "Сповіщення підтверджено." if activated else "Посилання недійсне або вже використане."
    return Response(
        f"<!doctype html><meta charset=utf-8><title>UA-Dim</title><p>{message}</p>",
        status=200,
        content_type="text/html; charset=utf-8",
    )


@listing_bp.route("/api/alerts/unsubscribe", methods=["GET", "POST"])
@limiter.limit("30 per hour")
def unsubscribe_listing_alert():
    from app import (
        _parse_alert_action_token,
        get_db,
        strip,
    )
    def hardened_response(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    token = strip(request.args.get("token") or request.form.get("token"), 1000)
    if request.method != "POST":
        safe_token = escape(token, quote=True)
        response = Response(
            "<!doctype html><html lang='uk'><meta charset=utf-8>"
            "<meta name='robots' content='noindex,nofollow'>"
            "<title>Відписатися — UA-Dim</title>"
            "<body><main><h1>Відписатися від сповіщень?</h1>"
            "<p>Підтвердьте дію кнопкою нижче. Відкриття цього посилання "
            "не змінює ваші налаштування.</p>"
            "<form method='post' action='/api/alerts/unsubscribe'>"
            f"<input type='hidden' name='token' value='{safe_token}'>"
            "<button type='submit'>Відписатися</button>"
            "</form></main></body></html>",
            status=200,
            content_type="text/html; charset=utf-8",
        )
        return hardened_response(response)

    parsed = _parse_alert_action_token(token, "unsubscribe")
    db = get_db()
    if parsed:
        alert_id, version = parsed
        anchor = db.execute(
            """
            SELECT email_normalized
            FROM listing_alerts
            WHERE id = ? AND unsubscribe_version = ?
            """,
            (alert_id, version),
        ).fetchone()
        if anchor:
            db.execute(
            """
            UPDATE listing_alerts
            SET is_active = 0, verification_token_hash = NULL,
                verification_expires_at = NULL,
                unsubscribe_version = unsubscribe_version + 1
            WHERE email_normalized = ?
            """,
                (anchor["email_normalized"],),
            )
        db.commit()
    if request.form:
        return hardened_response(Response(
            "<!doctype html><meta charset=utf-8><title>UA-Dim</title>"
            "<p>Сповіщення вимкнено. Якщо запит уже було оброблено, "
            "додаткових дій не потрібно.</p>",
            status=200,
            content_type="text/html; charset=utf-8",
        ))
    return hardened_response(jsonify(ok=True))


@listing_bp.route("/api/alerts/dispatch", methods=["GET", "POST"])
def dispatch_listing_alerts():
    from app import (
        alerts_dispatch_authorized,
        get_db,
        nonneg_int,
        run_dispatch_with_logging,
        strip,
        truthy_flag,
    )
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


@listing_bp.route("/api/alerts/dispatch/health", methods=["GET"])
def dispatch_listing_alerts_health():
    from app import (
        _parse_dt,
        alerts_dispatch_authorized,
        get_db,
    )
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


def _listing_recommendations(db, listing_id: int, limit: int = 6) -> list[dict] | None:
    from app import _row_to_listing
    source = db.execute(
        "SELECT id, city, district, property_type, rooms, price FROM listings WHERE id = ?",
        (listing_id,),
    ).fetchone()
    if not source:
        return None

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
    return [item[1] for item in scored[:limit]]


@listing_bp.route("/api/recommendations", methods=["GET"])
def get_recommendations():
    from app import (
        get_db,
        nonneg_int,
    )
    db = get_db()
    listing_id = nonneg_int(request.args.get("listing_id"))
    limit = nonneg_int(request.args.get("limit")) or 6
    limit = min(max(limit, 1), 20)

    if listing_id is None:
        return jsonify(error="listing_id is required"), 422

    recommendations = _listing_recommendations(db, listing_id, limit)
    if recommendations is None:
        return jsonify(error="Оголошення не знайдено"), 404
    return jsonify(recommendations=recommendations)


# ─── Map (geo-based search) ──────────────────────────────────────────────────

@listing_bp.route("/api/map/listings", methods=["GET"])
def get_map_listings():
    """Get listings with coordinates for map visualization."""
    from app import (
        get_db,
        nonneg_int,
        pos_int,
        strip,
    )
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
          AND l.status = 'published' AND l.listing_status = 'active'
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
    from app import strip
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


@listing_bp.route("/api/analytics/summary", methods=["GET"])
def analytics_summary():
    from app import get_db
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


@listing_bp.route("/api/analytics/lead-funnel", methods=["POST"])
@limiter.limit("120 per minute")
def analytics_lead_funnel_event():
    from app import (
        _upsert_lead_funnel_summary,
        cache_delete_prefix,
        get_db,
        strip,
    )
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


@listing_bp.route("/api/leads", methods=["POST"])
@limiter.limit("30 per minute")
def create_lead_request():
    from app import (
        _development_project_by_slug,
        _upsert_lead_funnel_summary,
        cache_delete_prefix,
        get_db,
        nonneg_int,
        strip,
        truthy_flag,
        validate_email,
    )
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


def _serialize_listing_inquiry(row) -> dict:
    return {
        "id": row["id"],
        "listing_id": row["listing_id"],
        "listing_title": row["listing_title"],
        "name": row["name"],
        "phone": row["phone"],
        "email": row["email"],
        "message": row["message"] or "",
        "preferred_channel": row["preferred_channel"] or "phone",
        "status": row["status"] or "new",
        "response_message": row["response_message"] or "",
        "responded_at": row["responded_at"],
        "created_at": row["created_at"],
    }


@listing_bp.route("/api/listings/<int:listing_id>/inquiries", methods=["POST"])
@limiter.limit("10 per minute")
def create_listing_inquiry(listing_id: int):
    from app import (
        _upsert_lead_funnel_summary,
        cache_delete_prefix,
        get_db,
        strip,
        validate_email,
    )
    db = get_db()
    listing = db.execute(
        "SELECT id, listing_type, price FROM listings WHERE id = ? AND status = 'published'",
        (listing_id,),
    ).fetchone()
    if not listing:
        return jsonify(error="Оголошення не знайдено"), 404

    data = _parse_json_payload()
    name = strip(data.get("name", ""), 120)
    phone = re.sub(r"[\s()-]+", "", strip(data.get("phone", ""), 40))
    email = strip(data.get("email", ""), 254).lower()
    message = strip(data.get("message", ""), 1200)
    preferred_channel = strip(data.get("preferred_channel", "phone"), 16).lower()
    session_id = strip(data.get("session_id", ""), 80)

    if len(name) < 2:
        return jsonify(error="Вкажіть ім'я"), 422
    if not phone and not email:
        return jsonify(error="Вкажіть телефон або email"), 422
    if phone and not re.match(r"^\+?\d{7,15}$", phone):
        return jsonify(error="Невірний формат номера телефону"), 422
    if email and not validate_email(email):
        return jsonify(error="Невірний формат email"), 422
    if preferred_channel not in {"phone", "email", "chat"}:
        return jsonify(error="Невідомий спосіб зв'язку"), 422
    if preferred_channel == "phone" and not phone:
        return jsonify(error="Для дзвінка вкажіть телефон"), 422
    if preferred_channel == "email" and not email:
        return jsonify(error="Для email вкажіть адресу"), 422

    now = datetime.datetime.utcnow().replace(microsecond=0)
    duplicate_cutoff = (now - datetime.timedelta(minutes=2)).isoformat(sep=" ")
    duplicate = db.execute(
        """
        SELECT id FROM lead_requests
        WHERE lead_type = 'inquiry' AND listing_id = ?
          AND COALESCE(phone, '') = ? AND COALESCE(email, '') = ?
          AND created_at >= ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (listing_id, phone, email, duplicate_cutoff),
    ).fetchone()
    if duplicate:
        return jsonify(ok=True, inquiry_id=duplicate["id"], duplicate=True), 200

    created_at = now.isoformat(sep=" ")
    cursor = db.execute(
        """
        INSERT INTO lead_requests (
            lead_type, source, name, phone, email, message, listing_id,
            session_id, preferred_channel, status, created_at
        ) VALUES ('inquiry', 'listing_page', ?, ?, ?, ?, ?, ?, ?, 'new', ?)
        """,
        (
            name,
            phone or None,
            email or None,
            message or None,
            listing_id,
            session_id or None,
            preferred_channel,
            created_at,
        ),
    )
    db.execute(
        """
        INSERT INTO lead_funnel_events (
            listing_id, event, intent, source, listing_type, price, session_id, created_at
        ) VALUES (?, 'lead_submit', 'listing_inquiry', 'listing_page', ?, ?, ?, ?)
        """,
        (
            listing_id,
            listing["listing_type"] or "unknown",
            listing["price"],
            session_id or None,
            created_at,
        ),
    )
    _upsert_lead_funnel_summary(
        db,
        day=now.strftime("%Y-%m-%d"),
        source="listing_page",
        listing_type=listing["listing_type"] or "unknown",
        event="lead_submit",
        listing_id=listing_id,
        created_at=created_at,
        session_id=session_id or None,
    )
    db.commit()
    cache_delete_prefix("admin:reports:lead-funnel:")
    return jsonify(ok=True, inquiry_id=cursor.lastrowid, duplicate=False), 201


@listing_bp.route("/api/inquiries", methods=["GET"])
@require_auth
def list_listing_inquiries():
    from app import get_db
    db = get_db()
    rows = db.execute(
        """
        SELECT lr.id, lr.listing_id, l.title AS listing_title, lr.name, lr.phone,
               lr.email, lr.message, lr.preferred_channel, lr.status,
               lr.response_message, lr.responded_at, lr.created_at
        FROM lead_requests lr
        JOIN listings l ON l.id = lr.listing_id
        WHERE lr.lead_type = 'inquiry' AND l.user_id = ?
        ORDER BY CASE lr.status WHEN 'new' THEN 0 WHEN 'viewed' THEN 1 ELSE 2 END,
                 lr.created_at DESC
        LIMIT 250
        """,
        (g.user_id,),
    ).fetchall()
    return jsonify(inquiries=[_serialize_listing_inquiry(row) for row in rows])


@listing_bp.route("/api/inquiries/<int:inquiry_id>", methods=["PATCH"])
@require_auth
@limiter.limit("60 per minute")
def update_listing_inquiry(inquiry_id: int):
    from app import (
        cache_delete_prefix,
        get_db,
        strip,
    )
    db = get_db()
    row = db.execute(
        """
        SELECT lr.id, lr.listing_id, lr.status, l.listing_type, l.price
        FROM lead_requests lr
        JOIN listings l ON l.id = lr.listing_id
        WHERE lr.id = ? AND lr.lead_type = 'inquiry' AND l.user_id = ?
        """,
        (inquiry_id, g.user_id),
    ).fetchone()
    if not row:
        return jsonify(error="Заявку не знайдено"), 404

    data = _parse_json_payload()
    status = strip(data.get("status", row["status"]), 16).lower()
    response_message = strip(data.get("response_message", ""), 1200)
    if status not in {"new", "viewed", "responded", "closed"}:
        return jsonify(error="Невідомий статус заявки"), 422
    allowed_transitions = {
        "new": {"new", "viewed", "responded", "closed"},
        "viewed": {"viewed", "responded", "closed"},
        "responded": {"responded", "closed"},
        "closed": {"closed"},
    }
    if status not in allowed_transitions.get(row["status"] or "new", set()):
        return jsonify(error="Неможливо повернути заявку до попереднього статусу"), 409
    if status == "responded" and not response_message:
        return jsonify(error="Додайте коротку відповідь"), 422

    responded_at = (
        datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
        if status == "responded"
        else None
    )
    db.execute(
        """
        UPDATE lead_requests
        SET status = ?, response_message = CASE WHEN ? = '' THEN response_message ELSE ? END,
            responded_at = COALESCE(?, responded_at)
        WHERE id = ?
        """,
        (status, response_message, response_message, responded_at, inquiry_id),
    )
    if status == "responded" and row["status"] != "responded":
        db.execute(
            """
            INSERT INTO lead_funnel_events (
                listing_id, event, intent, source, listing_type, price, created_at
            ) VALUES (?, 'seller_response', 'listing_inquiry', 'seller_cabinet', ?, ?, ?)
            """,
            (
                row["listing_id"],
                row["listing_type"] or "unknown",
                row["price"],
                responded_at,
            ),
        )
    db.commit()
    cache_delete_prefix("admin:reports:lead-funnel:")
    return jsonify(ok=True, status=status, responded_at=responded_at)


@listing_bp.route("/api/analytics/client-telemetry", methods=["POST"])
@limiter.limit("120 per hour")
def analytics_client_telemetry():
    from app import (
        cache_delete_prefix,
        get_db,
        strip,
    )
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


@listing_bp.route("/api/analytics/web-vitals", methods=["POST"])
@limiter.limit("600 per hour")
def analytics_web_vitals():
    from app import (
        cache_delete_prefix,
        get_db,
        strip,
    )
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
