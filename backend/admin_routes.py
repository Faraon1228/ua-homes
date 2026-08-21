"""
UA Homes Admin API Routes
Endpoints for admin panel property/user management
"""

from flask import Blueprint, g, jsonify, make_response, request, Response
from functools import wraps
from enum import Enum
import datetime
import csv
import hmac
import io
import json
import os
import re
import secrets
from urllib.parse import urlsplit

from app import limiter

# Create blueprint
admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


class StaffRole(str, Enum):
    ADMIN = "admin"
    MODERATOR = "moderator"


class Permission(str, Enum):
    ADMIN_ONLY = "admin/all"
    DASHBOARD_READ = "dashboard/read"
    LISTINGS_READ = "listings/read"
    LISTINGS_WRITE = "listings/write"
    LISTINGS_MODERATE = "listings/moderate"
    VERIFICATIONS_MANAGE = "verifications/manage"
    REPORTS_MANAGE = "reports/manage"
    AUDIT_READ = "audit/read"
    USERS_MANAGE = "users/manage"
    LEADS_MANAGE = "leads/manage"
    AGENCIES_MANAGE = "agencies/manage"
    DEVELOPERS_MANAGE = "developers/manage"
    SYSTEM_READ = "system/read"


MODERATOR_PERMISSIONS = frozenset({
    Permission.DASHBOARD_READ.value,
    Permission.LISTINGS_READ.value,
    Permission.LISTINGS_MODERATE.value,
    Permission.VERIFICATIONS_MANAGE.value,
    Permission.REPORTS_MANAGE.value,
    Permission.AUDIT_READ.value,
})
ROLE_PERMISSIONS = {
    StaffRole.ADMIN.value: frozenset(permission.value for permission in Permission),
    StaffRole.MODERATOR.value: MODERATOR_PERMISSIONS,
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ADMIN_COOKIE = "ua_dim_staff_session"
CSRF_COOKIE = "ua_dim_staff_csrf"
LISTING_IMAGE_INSERT_SQL = (
    'INSERT INTO listing_images (listing_id, image_url, "order") VALUES (?, ?, ?)'
)
_SENSITIVE_AUDIT_KEYS = {
    "password", "password_hash", "token", "authorization", "csrf_token",
    "reporter_fingerprint", "phone", "email", "message", "details",
}


def _staff_permissions(role):
    return sorted(ROLE_PERMISSIONS.get(str(role or ""), ()))


def _request_origin_allowed():
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    origin_host = (parsed.hostname or "").lower()
    request_host = (request.host.split(":", 1)[0] or "").lower()
    if origin_host == request_host:
        return True
    configured = {
        urlsplit(value.strip()).hostname
        for value in os.environ.get("UA_HOMES_CORS_ORIGINS", "").split(",")
        if value.strip()
    }
    return origin_host in {
        "ua-homes.netlify.app", "ua-dim.netlify.app", "ua-dom.com",
        "www.ua-dom.com", "ua-dim.com", "www.ua-dim.com",
    } | {host.lower() for host in configured if host}


def _audit_metadata():
    payload = request.get_json(silent=True)
    keys = sorted(
        str(key)[:80]
        for key in payload.keys()
        if isinstance(payload, dict)
        and str(key).lower() not in _SENSITIVE_AUDIT_KEYS
    )[:30] if isinstance(payload, dict) else []
    return json.dumps(
        {"changed_fields": keys},
        ensure_ascii=True,
        separators=(",", ":"),
    )


def record_admin_audit(db, *, action, permission, resource_type, resource_id=None):
    db.execute(
        """
        INSERT INTO admin_audit_log (
            actor_id, actor_role, action, permission, resource_type,
            resource_id, metadata_json, request_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            g.user_id,
            g.staff_role,
            str(action)[:120],
            str(permission)[:80],
            str(resource_type)[:80],
            None if resource_id is None else str(resource_id)[:120],
            _audit_metadata(),
            str(getattr(g, "request_id", "unknown"))[:128],
        ),
    )


def require_permission(permission):
    permission_value = permission.value if isinstance(permission, Permission) else str(permission)

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            from app import decode_token, get_db, token_matches_user_version
            import jwt

            authorization = request.headers.get("Authorization", "")
            cookie_auth = not authorization.startswith("Bearer ")
            token = request.cookies.get(ADMIN_COOKIE, "") if cookie_auth else authorization[7:]
            try:
                payload = decode_token(token)
                user_id = int(payload["sub"])
            except (jwt.PyJWTError, KeyError, TypeError, ValueError):
                return jsonify(error="Unauthorized"), 401

            db = get_db()
            user = db.execute(
                """
                SELECT id, email, name, role, auth_token_version, status
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            if (
                not user
                or user["status"] != "active"
                or not token_matches_user_version(payload, user)
            ):
                return jsonify(error="Unauthorized"), 401
            if user["role"] not in ROLE_PERMISSIONS:
                return jsonify(error="Forbidden"), 403

            permissions = ROLE_PERMISSIONS[user["role"]]
            if (
                permission_value != Permission.ADMIN_ONLY.value
                and permission_value not in permissions
            ) or (
                permission_value == Permission.ADMIN_ONLY.value
                and user["role"] != StaffRole.ADMIN.value
            ):
                return jsonify(error="Forbidden"), 403

            if request.method not in SAFE_METHODS:
                if not _request_origin_allowed():
                    return jsonify(error="Invalid request origin"), 403
                if cookie_auth:
                    supplied = request.headers.get("X-CSRF-Token", "")
                    expected = request.cookies.get(CSRF_COOKIE, "")
                    if (
                        not _valid_csrf_token(expected)
                        or not _valid_csrf_token(supplied)
                        or not hmac.compare_digest(supplied, expected)
                    ):
                        return jsonify(error="CSRF validation failed"), 403

            g.user_id = user_id
            g.user_email = user["email"]
            g.staff_role = user["role"]
            g.staff_permissions = sorted(permissions)
            if request.method not in SAFE_METHODS:
                route_values = request.view_args or {}
                resource_id = next(iter(route_values.values()), None)
                resource_type = (
                    request.endpoint.rsplit(".", 1)[-1].replace("admin_", "")
                    if request.endpoint else "admin"
                )
                record_admin_audit(
                    db,
                    action=f"{request.method.lower()}:{resource_type}",
                    permission=permission_value,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
            result = f(*args, **kwargs)
            response = make_response(result)
            if request.method not in SAFE_METHODS and response.status_code >= 400:
                db.rollback()
            return response
        return wrapper
    return decorator


def require_auth_admin(f):
    """Backward-compatible admin-only decorator."""
    return require_permission(Permission.ADMIN_ONLY)(f)


def log_moderation_action(db, listing_id, action, reason=None):
    db.execute(
        "INSERT INTO moderation_log (listing_id, admin_id, action, reason) VALUES (?, ?, ?, ?)",
        (listing_id, g.user_id, action, reason)
    )


def apply_public_listing_side_effects(db, published_listing_ids=()):
    from app import cache_delete_prefix, run_dispatch_with_logging

    cache_delete_prefix("public:listings:")
    for listing_id in dict.fromkeys(int(value) for value in published_listing_ids):
        run_dispatch_with_logging(
            db,
            trigger_type="listing_update_published",
            listing_id=listing_id,
            dry_run=False,
            raise_errors=False,
        )


def parse_csv_bool(value):
    return str(value).strip().lower() in {"1", "true", "yes", "y", "так", "дa", "да"}


def parse_csv_images(value):
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()][:10]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.split(",") if part.strip()][:10]


def _cutoff_date(days: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=days)).isoformat()


def _cutoff_datetime(hours: int) -> str:
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def parse_pagination(args, *, default_limit=50, max_limit=200):
    try:
        limit = int(args.get("limit", default_limit))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit and offset must be integers") from exc
    if limit < 1 or limit > max_limit:
        raise ValueError(f"limit must be between 1 and {max_limit}")
    if offset < 0 or offset > 1_000_000:
        raise ValueError("offset must be between 0 and 1000000")
    return limit, offset


def parse_csv_row(row, row_number):
    required = ["title", "city", "district", "price", "rooms", "area"]
    missing = [field for field in required if not str(row.get(field) or "").strip()]
    if missing:
        return None, f"Row {row_number}: missing required fields: {', '.join(missing)}"

    try:
        price = int(float(row.get("price")))
        rooms = int(float(row.get("rooms")))
        area = float(row.get("area"))
        floor = int(float(row.get("floor", 1) or 1))
        total_floors = int(float(row.get("total_floors", 1) or 1))
        year_built = row.get("year_built")
        year_built = int(float(year_built)) if str(year_built or "").strip() else None
        latitude = row.get("latitude")
        latitude = float(latitude) if str(latitude or "").strip() else None
        longitude = row.get("longitude")
        longitude = float(longitude) if str(longitude or "").strip() else None
    except (TypeError, ValueError) as exc:
        return None, f"Row {row_number}: invalid number value ({exc})"

    status = (row.get("status") or "draft").strip().lower()
    if status not in {"draft", "published", "pending", "rejected", "archived"}:
        status = "draft"

    property_type = (row.get("property_type") or "квартира").strip() or "квартира"
    condition_type = (row.get("condition_type") or "вторинка").strip() or "вторинка"

    listing = {
        "title": str(row.get("title")).strip()[:200],
        "city": str(row.get("city")).strip()[:100],
        "district": str(row.get("district")).strip()[:100],
        "property_type": property_type[:50],
        "condition_type": condition_type[:50],
        "price": price,
        "rooms": rooms,
        "area": area,
        "floor": floor,
        "total_floors": total_floors,
        "year_built": year_built,
        "e_oselya": 1 if parse_csv_bool(row.get("e_oselya")) else 0,
        "description": str(row.get("description") or "").strip()[:2000],
        "status": status,
        "latitude": latitude,
        "longitude": longitude,
        "images": json.dumps(parse_csv_images(row.get("images"))),
    }
    return listing, None


def moderation_state_for_action(action):
    return {
        "approve": "approved",
        "reject": "rejected",
        "hold": "pending_review",
        "review": "in_review",
        "changes_requested": "changes_requested",
    }.get(action)


def listing_status_for_moderation(moderation_status):
    if moderation_status == "approved":
        return "published"
    if moderation_status == "rejected":
        return "rejected"
    return "pending"


def build_listing_filters(args, allow_ids=False):
    clauses = []
    params = []

    if allow_ids:
        ids_arg = (args.get("listing_ids") or "").strip()
        if ids_arg:
            try:
                ids = [int(item) for item in ids_arg.split(",") if item.strip()]
            except ValueError:
                raise ValueError("listing_ids must contain integers")
            if not ids:
                raise ValueError("listing_ids cannot be empty")
            if len(ids) > 200:
                raise ValueError("listing_ids may contain at most 200 values")
            clauses.append(f"id IN ({','.join('?' for _ in ids)})")
            params.extend(ids)

    city = (args.get("city") or "").strip()
    status = (args.get("status") or "").strip()
    search = (args.get("search") or "").strip()
    if len(city) > 100:
        raise ValueError("city must be at most 100 characters")
    if status and status not in {"draft", "published", "pending", "rejected", "archived"}:
        raise ValueError("Invalid listing status")
    if len(search) > 120:
        raise ValueError("search must be at most 120 characters")

    if city:
        clauses.append("city = ?")
        params.append(city)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if search:
        clauses.append("(title LIKE ? OR district LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term])

    return clauses, params


# ─── Admin Auth ──────────────────────────────────────────────────────

@admin_bp.route("/auth/register", methods=["POST"])
def admin_register():
    """Register new admin (first admin only, localhost only)"""
    from app import _refresh_user_growth_summary, cache_delete_prefix, get_db
    import bcrypt
    
    # Allow only localhost
    if request.remote_addr not in ['127.0.0.1', 'localhost', '::1']:
        return jsonify(error="Admin registration only from localhost"), 403
    
    db = get_db()
    
    # Check if any admin exists
    existing_admin = db.execute(
        "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
    ).fetchone()
    
    if existing_admin:
        return jsonify(error="Admin already exists"), 409
    
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    email_value = data.get("email")
    password_value = data.get("password")
    name_value = data.get("name", "Admin")
    if (
        not isinstance(email_value, str)
        or not isinstance(password_value, str)
        or not isinstance(name_value, str)
    ):
        return jsonify(error="Invalid registration fields"), 400
    email = email_value.strip()
    password = password_value
    name = name_value.strip() or "Admin"
    
    if not email or not password:
        return jsonify(error="Email and password required"), 400
    
    if len(password) < 8:
        return jsonify(error="Password must be 8+ characters"), 400
    
    if '@' not in email:
        return jsonify(error="Invalid email"), 400
    
    # Check if user exists
    if db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify(error="Email already registered"), 409
    
    # Hash password
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    # Create admin user
    db.execute(
        "INSERT INTO users (name, email, password, password_hash, role, status) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, hashed, hashed, 'admin', 'active')
    )
    _refresh_user_growth_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:user-growth:")
    
    return jsonify(
        ok=True,
        message="Admin account created. Please login."
    ), 201


@admin_bp.route("/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def admin_login():
    """Authenticate an active staff member."""
    from app import _password_matches, get_db, make_token

    if not _request_origin_allowed():
        return jsonify(error="Invalid request origin"), 403
    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Invalid credentials"), 401
    email_value = data.get("email")
    password_value = data.get("password")
    if not isinstance(email_value, str) or not isinstance(password_value, str):
        return jsonify(error="Invalid credentials"), 401
    email = email_value.strip()
    password = password_value

    user = db.execute(
        """
        SELECT id, name, email, password, password_hash, role,
               auth_token_version, status
        FROM users WHERE email = ?
        """,
        (email,)
    ).fetchone()
    stored_password = (user["password_hash"] or user["password"]) if user else None
    if (
        not user
        or user["role"] not in ROLE_PERMISSIONS
        or user["status"] != "active"
        or not _password_matches(password, stored_password)
    ):
        return jsonify(error="Invalid credentials"), 401

    token = make_token(user["id"], user["email"], user["auth_token_version"])
    csrf_token = secrets.token_urlsafe(32)
    response = jsonify(
        ok=True,
        token=token,
        csrf_token=csrf_token,
        staff={
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "permissions": _staff_permissions(user["role"]),
        },
    )
    secure = _staff_cookie_secure()
    response.set_cookie(
        ADMIN_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="Strict",
        max_age=JWT_EXP_HOURS_SECONDS,
        path="/api/admin",
    )
    _set_csrf_cookie(response, csrf_token)
    response.headers["Cache-Control"] = "no-store"
    return response


JWT_EXP_HOURS_SECONDS = 72 * 60 * 60


def _staff_cookie_secure():
    local_http = request.host.split(":", 1)[0] in {"localhost", "127.0.0.1"}
    return request.is_secure or not local_http


def _valid_csrf_token(value):
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value)
    )


def _set_csrf_cookie(response, csrf_token):
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=True,
        secure=_staff_cookie_secure(),
        samesite="Strict",
        max_age=JWT_EXP_HOURS_SECONDS,
        path="/api/admin",
    )


@admin_bp.route("/auth/session", methods=["GET"])
@require_permission(Permission.DASHBOARD_READ)
def admin_session():
    from app import get_db

    user = get_db().execute(
        "SELECT id, name, email, role FROM users WHERE id = ?",
        (g.user_id,),
    ).fetchone()
    csrf_token = request.cookies.get(CSRF_COOKIE, "")
    if not _valid_csrf_token(csrf_token):
        csrf_token = secrets.token_urlsafe(32)
    response = jsonify(
        csrf_token=csrf_token,
        staff={
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "permissions": g.staff_permissions,
        }
    )
    _set_csrf_cookie(response, csrf_token)
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_bp.route("/auth/logout", methods=["POST"])
@require_permission(Permission.DASHBOARD_READ)
def admin_logout():
    from app import get_db

    db = get_db()
    db.execute(
        "UPDATE users SET auth_token_version = auth_token_version + 1 WHERE id = ?",
        (g.user_id,),
    )
    db.commit()
    response = jsonify(ok=True)
    response.delete_cookie(ADMIN_COOKIE, path="/api/admin")
    response.delete_cookie(CSRF_COOKIE, path="/api/admin")
    response.headers["Cache-Control"] = "no-store"
    return response


# ─── Admin Dashboard ─────────────────────────────────────────────────

@admin_bp.route("/dashboard/overview", methods=["GET"])
@admin_bp.route("/dashboard/stats", methods=["GET"])
@require_permission(Permission.DASHBOARD_READ)
def dashboard_stats():
    """Get dashboard statistics"""
    from app import get_db

    period = (request.args.get("period") or "30d").strip().lower()
    period_days = {"7d": 7, "30d": 30, "90d": 90}.get(period)
    if period_days is None:
        return jsonify(error="period must be one of: 7d, 30d, 90d"), 400
    db = get_db()
    
    total_listings = db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    published_listings = db.execute(
        "SELECT COUNT(*) FROM listings WHERE status = 'published'"
    ).fetchone()[0]
    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_agents = db.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'agent'"
    ).fetchone()[0]
    
    avg_price = db.execute(
        "SELECT ROUND(AVG(price)) FROM listings WHERE status = 'published'"
    ).fetchone()[0] or 0
    
    # Listings by city (top 5)
    by_city = db.execute(
        "SELECT city, COUNT(*) as count FROM listings WHERE status = 'published' "
        "GROUP BY city ORDER BY count DESC LIMIT 5"
    ).fetchall()
    
    # Recent activity
    recent = db.execute(
        "SELECT id, title, city, price, created_at FROM listings "
        "ORDER BY created_at DESC LIMIT 5"
    ).fetchall()

    backlog = {
        "moderation": int(db.execute(
            """
            SELECT COUNT(*) FROM listings
            WHERE status IN ('draft', 'pending')
               OR moderation_status IN ('pending_review', 'in_review', 'changes_requested')
            """
        ).fetchone()[0] or 0),
        "verifications": int(db.execute(
            """
            SELECT COUNT(*) FROM listings
            WHERE listing_verification_status = 'pending'
               OR owner_verification_status = 'pending'
               OR phone_verification_status = 'pending'
            """
        ).fetchone()[0] or 0),
        "reports": int(db.execute(
            "SELECT COUNT(*) FROM listing_reports WHERE status = 'pending'"
        ).fetchone()[0] or 0),
    }
    cutoff = _cutoff_date(period_days)
    trend_rows = db.execute(
        """
        SELECT SUBSTR(created_at, 1, 10) AS day, COUNT(*) AS listings_created
        FROM listings
        WHERE created_at >= ?
        GROUP BY SUBSTR(created_at, 1, 10)
        ORDER BY day ASC
        """,
        (cutoff,),
    ).fetchall()

    return jsonify(
        total_listings=total_listings,
        published_listings=published_listings,
        total_users=total_users,
        total_agents=total_agents,
        avg_price=int(avg_price),
        by_city=[dict(row) for row in by_city],
        recent_listings=[dict(row) for row in recent],
        period=period,
        kpis={
            "total_listings": int(total_listings),
            "published_listings": int(published_listings),
            "total_users": int(total_users),
            "total_agents": int(total_agents),
            "avg_price": int(avg_price),
        },
        backlog=backlog,
        trends={"listings_created": [dict(row) for row in trend_rows]},
    )


# ─── Admin Listings Management ──────────────────────────────────────────

@admin_bp.route("/listings", methods=["GET"])
@require_permission(Permission.LISTINGS_READ)
def admin_get_listings():
    """Get all listings with filters for admin"""
    from app import get_db
    
    db = get_db()
    args = request.args
    
    try:
        limit, offset = parse_pagination(args)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    
    query = """
        SELECT id, title, city, district, price, rooms, area, status, 
               created_at, views, e_oselya, images, listing_highlights, capture_mode,
               property_type, condition_type, listing_status, source, has_photo_tour, has_video_tour
        FROM listings WHERE 1=1
    """
    try:
        clauses, params = build_listing_filters(args)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    for clause in clauses:
        query += f" AND {clause}"
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = db.execute(query, params).fetchall()
    
    total_query = "SELECT COUNT(*) FROM listings WHERE 1=1"
    total_params = list(params[:-2])
    for clause in clauses:
        total_query += f" AND {clause}"
    total = db.execute(total_query, total_params).fetchone()[0]
    
    return jsonify(
        listings=[dict(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset
    )


@admin_bp.route("/listings", methods=["POST"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_create_listing():
    """Create new listing as admin"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db
    
    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    
    required = ['title', 'city', 'district', 'price', 'rooms', 'area']
    if not all(str(data.get(key) or "").strip() for key in required):
        return jsonify(error=f"Missing required fields: {required}"), 400
    
    try:
        price = int(data['price'])
        rooms = int(data['rooms'])
        area = float(data['area'])
    except (ValueError, TypeError):
        return jsonify(error="Price/rooms/area must be numbers"), 400
    if price <= 0 or rooms < 0 or area <= 0:
        return jsonify(error="Price and area must be positive; rooms cannot be negative"), 400
    for field, maximum in (("title", 200), ("city", 100), ("district", 100)):
        if len(str(data[field]).strip()) > maximum:
            return jsonify(error=f"{field} is too long"), 400
    
    status = str(data.get('status') or 'draft').strip().lower()
    if status not in {'draft', 'published', 'pending', 'rejected', 'archived'}:
        return jsonify(error="Invalid listing status"), 400
    listing_status = str(data.get('listing_status') or data.get('listingStatus') or 'active').strip().lower()
    if listing_status not in {'active', 'sold', 'removed'}:
        return jsonify(error="Invalid listing lifecycle status"), 400
    now = datetime.datetime.utcnow().isoformat(timespec='seconds')

    cur = db.execute("""
        INSERT INTO listings 
        (title, city, district, property_type, condition_type, price, rooms, area,
        floor, total_floors, year_built, e_oselya, description, status, listing_status, moderation_status, moderation_updated_at, published_at, user_id,
        latitude, longitude, source, has_photo_tour, has_video_tour, listing_highlights, capture_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data['title'],
        data['city'],
        data['district'],
        data.get('property_type', 'квартира'),
        data.get('condition_type', 'невідомо'),
        price,
        rooms,
        area,
        data.get('floor', 1),
        data.get('total_floors', 1),
        data.get('year_built'),
        1 if data.get('e_oselya') else 0,
        data.get('description', ''),
        status,
        listing_status,
        'approved' if status == 'published' else 'pending_review',
        now if status == 'published' else None,
        now if status == 'published' else None,
        g.user_id,  # Admin as owner
        data.get('latitude'),
        data.get('longitude'),
        str(data.get('source') or 'owner').strip().lower(),
        1 if data.get('hasPhotoTour') else 0,
        1 if data.get('hasVideoTour') else 0,
        json.dumps(data.get('highlights') or [], ensure_ascii=False),
        str(data.get('captureMode') or 'off_site').strip().lower(),
    ))
    listing_id = cur.lastrowid
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    
    if status == "published":
        apply_public_listing_side_effects(db, (listing_id,))
    
    return jsonify(id=listing_id, ok=True), 201


@admin_bp.route("/listings/<int:listing_id>", methods=["GET"])
@require_permission(Permission.LISTINGS_READ)
def admin_get_listing(listing_id):
    """Get single listing details"""
    from app import get_db
    
    db = get_db()
    listing = db.execute(
        """SELECT id, title, city, district, price, rooms, area, floor,
                  total_floors, year_built, e_oselya, description, status,
                  listing_status,
                  property_type, condition_type, latitude, longitude, views,
                  source, has_photo_tour, has_video_tour, listing_highlights, capture_mode,
                  created_at FROM listings WHERE id = ?""",
        (listing_id,)
    ).fetchone()
    
    if not listing:
        return jsonify(error="Listing not found"), 404
    
    # Get images
    images = db.execute(
        'SELECT id, image_url FROM listing_images WHERE listing_id = ? ORDER BY "order"',
        (listing_id,)
    ).fetchall()
    
    result = dict(listing)
    result['images'] = [dict(img) for img in images]
    
    return jsonify(listing=result)


@admin_bp.route("/listings/<int:listing_id>", methods=["PUT"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_update_listing(listing_id):
    """Update listing"""
    from app import (
        _refresh_listing_city_summary,
        cache_delete_prefix,
        get_db,
        log_field_change,
    )
    
    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    now = datetime.datetime.utcnow().isoformat(timespec='seconds')
    
    existing = db.execute(
        """
        SELECT id, title, city, district, price, rooms, area, floor,
               total_floors, year_built, e_oselya, description, property_type,
               condition_type, latitude, longitude, status, listing_status,
               source, has_photo_tour, has_video_tour, listing_highlights,
               capture_mode
        FROM listings WHERE id = ?
        """,
        (listing_id,),
    ).fetchone()
    if not existing:
        return jsonify(error="Listing not found"), 404
    if "status" in data and str(data.get("status") or "").strip().lower() not in {
        "draft", "published", "pending", "rejected", "archived"
    }:
        return jsonify(error="Invalid listing status"), 400
    if "listing_status" in data and str(data.get("listing_status") or "").strip().lower() not in {
        "active", "sold", "removed"
    }:
        return jsonify(error="Invalid listing lifecycle status"), 400
    if "price" in data:
        try:
            price_value = int(data["price"])
            if price_value <= 0 or float(data["price"]) != price_value:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(error="price must be a positive integer"), 400
    if "area" in data:
        try:
            if float(data["area"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(error="area must be a positive number"), 400
    if "rooms" in data:
        try:
            if int(data["rooms"]) < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(error="rooms must be a non-negative integer"), 400
    
    # Build update query
    updates = []
    params = []
    
    allowed_fields = [
        'title', 'city', 'district', 'price', 'rooms', 'area',
        'floor', 'total_floors', 'year_built', 'e_oselya',
        'description', 'property_type', 'condition_type',
    'latitude', 'longitude', 'status', 'listing_status',
    'source', 'has_photo_tour', 'has_video_tour', 'listing_highlights', 'capture_mode'
    ]
    
    for field in allowed_fields:
        if field in data:
            value = data[field]
            if field in {'has_photo_tour', 'has_video_tour', 'e_oselya'}:
                value = 1 if bool(value) else 0
            elif field == 'price':
                value = int(value)
            elif field == 'rooms':
                value = int(value)
            elif field == 'area':
                value = float(value)
            elif field == 'listing_highlights' and isinstance(value, list):
                value = json.dumps(value, ensure_ascii=False)
            elif field in {'capture_mode', 'source', 'status', 'listing_status'} and value is not None:
                value = str(value).strip().lower()
            elif field in {'property_type', 'condition_type'} and value is not None:
                value = str(value).strip()
            log_field_change(
                db, listing_id, field, existing[field], value, "admin"
            )
            updates.append(f"{field} = ?")
            params.append(value)

    if 'status' in data:
        status = str(data.get('status') or '').strip().lower()
        moderation_status = 'approved' if status == 'published' else 'pending_review' if status in {'draft', 'pending'} else 'rejected' if status == 'rejected' else 'pending_review'
        updates.extend([
            "moderation_status = ?",
            "moderation_updated_at = ?",
            "published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, ?) ELSE published_at END",
        ])
        params.extend([moderation_status, now, status, now])
    
    if not updates:
        return jsonify(error="No fields to update"), 400
    
    params.append(listing_id)
    query = f"UPDATE listings SET {', '.join(updates)} WHERE id = ?"
    
    db.execute(query, params)
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    resulting_status = str(data.get("status") or existing["status"]).strip().lower()
    if existing["status"] == "published" or resulting_status == "published":
        newly_published = (
            (listing_id,)
            if existing["status"] != "published" and resulting_status == "published"
            else ()
        )
        apply_public_listing_side_effects(db, newly_published)
    
    return jsonify(ok=True, id=listing_id)


@admin_bp.route("/listings/<int:listing_id>", methods=["DELETE"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_delete_listing(listing_id):
    """Delete listing"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db
    
    db = get_db()
    
    existing = db.execute("SELECT id, status FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not existing:
        return jsonify(error="Listing not found"), 404
    
    # Delete images first
    db.execute("DELETE FROM listing_images WHERE listing_id = ?", (listing_id,))
    
    # Delete listing
    db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    if existing["status"] == "published":
        apply_public_listing_side_effects(db)
    
    return jsonify(ok=True)


@admin_bp.route("/listings/<int:listing_id>/duplicate", methods=["POST"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_duplicate_listing(listing_id):
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db
    import os
    import shutil

    db = get_db()
    source = db.execute(
        """
        SELECT title, city, district, property_type, condition_type, price, rooms,
               area, floor, total_floors, year_built, e_oselya, description,
               latitude, longitude, images
        FROM listings
        WHERE id = ?
        """,
        (listing_id,)
    ).fetchone()

    if not source:
        return jsonify(error="Listing not found"), 404

    title = source["title"] or "Listing"
    if not title.endswith(" (Copy)"):
        title = f"{title} (Copy)"

    cur = db.execute(
        """
        INSERT INTO listings (
            user_id, title, city, district, property_type, condition_type,
            price, rooms, area, floor, total_floors, year_built, e_oselya,
            views, images, status, latitude, longitude, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            g.user_id,
            title,
            source["city"],
            source["district"],
            source["property_type"],
            source["condition_type"],
            source["price"],
            source["rooms"],
            source["area"],
            source["floor"],
            source["total_floors"],
            source["year_built"],
            source["e_oselya"],
            0,
            source["images"],
            "draft",
            source["latitude"],
            source["longitude"],
            source["description"],
        )
    )

    new_listing_id = cur.lastrowid

    images = db.execute(
        'SELECT image_url, "order" as image_order FROM listing_images WHERE listing_id = ? ORDER BY "order"',
        (listing_id,)
    ).fetchall()
    new_image_rows = []
    for image in images:
        image_url = image["image_url"]
        if image_url.startswith("/images/listings/"):
            source_path = os.path.join("web", image_url.lstrip("/"))
            filename = os.path.basename(source_path)
            target_dir = os.path.join("web", "images", "listings", str(new_listing_id))
            os.makedirs(target_dir, exist_ok=True)
            target_path = os.path.join(target_dir, filename)
            if os.path.exists(source_path):
                shutil.copy2(source_path, target_path)
                image_url = f"/images/listings/{new_listing_id}/{filename}"
        new_image_rows.append((new_listing_id, image_url, image["image_order"]))

    for row in new_image_rows:
        db.execute(LISTING_IMAGE_INSERT_SQL, row)

    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    return jsonify(ok=True, id=new_listing_id, title=title), 201


@admin_bp.route("/listings/<int:listing_id>/publish", methods=["POST"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_publish_listing(listing_id):
    """Publish/unpublish listing"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, db_now_expr, get_db
    
    db = get_db()
    data = request.get_json() or {}
    published = data.get('published', True)
    existing = db.execute("SELECT status FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not existing:
        return jsonify(error="Listing not found"), 404
    
    status = 'published' if published else 'draft'
    
    db.execute(
        f"""
        UPDATE listings
        SET status = ?,
            moderation_status = ?,
            moderation_updated_at = {db_now_expr()},
            published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, {db_now_expr()}) ELSE published_at END
        WHERE id = ?
        """,
        (status, "approved" if published else "pending_review", status, listing_id)
    )
    log_moderation_action(db, listing_id, "publish" if published else "unpublish")
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    if existing["status"] == "published" or status == "published":
        newly_published = (
            (listing_id,)
            if existing["status"] != "published" and status == "published"
            else ()
        )
        apply_public_listing_side_effects(db, newly_published)
    
    return jsonify(ok=True, status=status)


@admin_bp.route("/import/csv", methods=["POST"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_import_csv():
    from app import _refresh_listing_city_summary, cache_delete_prefix, db_now_expr, get_db

    db = get_db()
    upload = request.files.get("file") or request.files.get("csv")
    if not upload:
        return jsonify(error="CSV file is required"), 400

    raw = upload.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        return jsonify(error="CSV header is required"), 400

    imported = []
    published_imports = []
    errors = []
    admin_id = g.user_id

    for row_number, row in enumerate(reader, start=2):
        listing, error = parse_csv_row(row, row_number)
        if error:
            errors.append(error)
            continue

        cur = db.execute(
            f"""
            INSERT INTO listings (
                user_id, title, city, district, property_type, condition_type,
                price, rooms, area, floor, total_floors, year_built, e_oselya,
                views, images, status, latitude, longitude, description,
                moderation_status, moderation_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {db_now_expr()})
            """,
            (
                admin_id,
                listing["title"],
                listing["city"],
                listing["district"],
                listing["property_type"],
                listing["condition_type"],
                listing["price"],
                listing["rooms"],
                listing["area"],
                listing["floor"],
                listing["total_floors"],
                listing["year_built"],
                listing["e_oselya"],
                0,
                listing["images"],
                listing["status"],
                listing["latitude"],
                listing["longitude"],
                listing["description"],
                "approved" if listing["status"] == "published" else "pending_review",
            ),
        )
        imported.append(cur.lastrowid)
        if listing["status"] == "published":
            published_imports.append(cur.lastrowid)

    if errors:
        db.rollback()
        return jsonify(error="CSV import failed", details=errors[:20]), 422

    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    if published_imports:
        apply_public_listing_side_effects(db, published_imports)
    return jsonify(ok=True, imported=len(imported), listing_ids=imported), 201


@admin_bp.route("/moderation/queue", methods=["GET"])
@require_permission(Permission.LISTINGS_MODERATE)
def admin_moderation_queue():
    from app import get_db

    db = get_db()
    try:
        limit, offset = parse_pagination(request.args)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    search = (request.args.get("search") or "").strip()
    if len(search) > 120:
        return jsonify(error="search must be at most 120 characters"), 400
    term = f"%{search}%"
    pending_where = """
        (status IN ('draft', 'pending', 'rejected')
         OR moderation_status IN ('in_review', 'changes_requested')
         OR owner_verification_status = 'pending'
         OR phone_verification_status = 'pending'
         OR listing_verification_status = 'pending')
    """
    params = []
    if search:
        pending_where += " AND (title LIKE ? OR city LIKE ? OR district LIKE ?)"
        params.extend([term, term, term])
    total = db.execute(
        f"SELECT COUNT(*) FROM listings WHERE {pending_where}",
        params,
    ).fetchone()[0]
    rows = db.execute(
        f"""
        SELECT id, title, city, district, price, rooms, area, status, created_at,
               moderation_status, moderation_reason,
               owner_verification_status, phone_verification_status,
               listing_verification_status
        FROM listings
        WHERE {pending_where}
        ORDER BY
            CASE
                WHEN owner_verification_status = 'pending' OR phone_verification_status = 'pending' THEN 0
                WHEN moderation_status IN ('changes_requested', 'in_review') THEN 1
                WHEN status IN ('pending', 'draft') THEN 2
                WHEN status = 'rejected' THEN 3
                ELSE 4
            END,
            created_at ASC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return jsonify(
        queue=[dict(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@admin_bp.route("/moderation/logs", methods=["GET"])
@require_permission(Permission.AUDIT_READ)
def admin_moderation_logs():
    from app import get_db

    db = get_db()
    try:
        limit, offset = parse_pagination(request.args)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    listing_id = request.args.get("listing_id")
    params = []
    where = ""
    if listing_id not in (None, ""):
        try:
            listing_id = int(listing_id)
        except ValueError:
            return jsonify(error="listing_id must be an integer"), 400
        where = "WHERE ml.listing_id = ?"
        params.append(listing_id)
    total = db.execute(
        f"SELECT COUNT(*) FROM moderation_log ml {where}",
        params,
    ).fetchone()[0]
    rows = db.execute(
        f"""
        SELECT ml.id, ml.listing_id, ml.action, ml.reason, ml.created_at,
               l.title, l.city,
               u.name AS admin_name
        FROM moderation_log ml
        JOIN listings l ON l.id = ml.listing_id
        LEFT JOIN users u ON u.id = ml.admin_id
        {where}
        ORDER BY ml.created_at DESC, ml.id DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return jsonify(
        logs=[dict(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@admin_bp.route("/listings/<int:listing_id>/moderate", methods=["POST"])
@require_permission(Permission.LISTINGS_MODERATE)
def admin_moderate_listing(listing_id):
    from app import (
        _refresh_listing_city_summary,
        cache_delete_prefix,
        db_now_expr,
        get_db,
    )

    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    action = (data.get("action") or "").strip().lower()
    reason = str(data.get("reason") or "").strip() or None
    if reason and len(reason) > 1000:
        return jsonify(error="reason must be at most 1000 characters"), 400
    owner_verification_status = (data.get("owner_verification_status") or "").strip().lower() or None
    phone_verification_status = (data.get("phone_verification_status") or "").strip().lower() or None

    listing = db.execute(
        """
        SELECT id, status, moderation_status, owner_verification_status, phone_verification_status
        FROM listings
        WHERE id = ?
        """,
        (listing_id,)
    ).fetchone()
    if not listing:
        return jsonify(error="Listing not found"), 404

    moderation_status = moderation_state_for_action(action)
    if not moderation_status:
        return jsonify(error="Invalid moderation action"), 400

    if owner_verification_status and owner_verification_status not in {"unverified", "pending", "verified", "rejected"}:
        return jsonify(error="Invalid owner verification status"), 400
    if phone_verification_status and phone_verification_status not in {"unverified", "pending", "verified", "rejected"}:
        return jsonify(error="Invalid phone verification status"), 400

    new_status = listing_status_for_moderation(moderation_status)
    next_owner_verification_status = owner_verification_status or listing["owner_verification_status"] or "unverified"
    next_phone_verification_status = phone_verification_status or listing["phone_verification_status"] or "unverified"

    db.execute(
        f"""
        UPDATE listings
        SET status = ?,
            moderation_status = ?,
            moderation_reason = ?,
            moderation_updated_at = {db_now_expr()},
            published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, {db_now_expr()}) ELSE published_at END,
            owner_verification_status = ?,
            phone_verification_status = ?,
            verified_owner = CASE WHEN ? = 'verified' THEN 1 ELSE 0 END,
            verified_phone = CASE WHEN ? = 'verified' THEN 1 ELSE 0 END
        WHERE id = ?
        """,
        (
            new_status,
            moderation_status,
            reason,
            new_status,
            next_owner_verification_status,
            next_phone_verification_status,
            next_owner_verification_status,
            next_phone_verification_status,
            listing_id,
        ),
    )
    log_moderation_action(db, listing_id, action, reason)
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    if listing["status"] == "published" or new_status == "published":
        newly_published = (
            (listing_id,)
            if listing["status"] != "published" and new_status == "published"
            else ()
        )
        apply_public_listing_side_effects(db, newly_published)

    return jsonify(
        ok=True,
        status=new_status,
        moderation_status=moderation_status,
        owner_verification_status=next_owner_verification_status,
        phone_verification_status=next_phone_verification_status,
    )


@admin_bp.route("/listings/bulk-moderate", methods=["POST"])
@require_permission(Permission.LISTINGS_MODERATE)
def admin_bulk_moderate():
    from app import (
        _refresh_listing_city_summary,
        cache_delete_prefix,
        db_now_expr,
        get_db,
    )

    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    action = (data.get("action") or "").strip().lower()
    reason = str(data.get("reason") or "").strip() or None
    if reason and len(reason) > 1000:
        return jsonify(error="reason must be at most 1000 characters"), 400
    listing_ids = data.get("listing_ids") or []

    if not isinstance(listing_ids, list) or not listing_ids:
        return jsonify(error="listing_ids must be a non-empty array"), 400
    if len(listing_ids) > 200:
        return jsonify(error="listing_ids may contain at most 200 values"), 400

    try:
        ids = [int(item) for item in listing_ids]
    except (TypeError, ValueError):
        return jsonify(error="listing_ids must contain integers"), 400

    moderation_status = moderation_state_for_action(action)
    if not moderation_status:
        return jsonify(error="Invalid moderation action"), 400
    new_status = listing_status_for_moderation(moderation_status)

    existing = db.execute(
        f"SELECT id, status FROM listings WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    ).fetchall()
    existing_ids = {row["id"] for row in existing}
    previously_unpublished_ids = {
        row["id"] for row in existing if row["status"] != "published"
    }
    missing = [listing_id for listing_id in ids if listing_id not in existing_ids]
    if missing:
        return jsonify(error="Some listings were not found", missing_ids=missing), 404

    for listing_id in ids:
        db.execute(
            f"""
            UPDATE listings
            SET status = ?,
                moderation_status = ?,
                moderation_reason = ?,
                moderation_updated_at = {db_now_expr()},
                published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, {db_now_expr()}) ELSE published_at END
            WHERE id = ?
            """,
            (new_status, moderation_status, reason, new_status, listing_id)
        )
        log_moderation_action(db, listing_id, action, reason)
    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    if new_status == "published" or any(row["status"] == "published" for row in existing):
        published_listing_ids = previously_unpublished_ids if new_status == "published" else ()
        apply_public_listing_side_effects(db, published_listing_ids)
    return jsonify(ok=True, status=new_status, moderation_status=moderation_status, updated=len(ids))


@admin_bp.route("/listings/bulk-delete", methods=["POST"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_bulk_delete():
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db

    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    listing_ids = data.get("listing_ids") or []

    if not isinstance(listing_ids, list) or not listing_ids:
        return jsonify(error="listing_ids must be a non-empty array"), 400
    if len(listing_ids) > 200:
        return jsonify(error="listing_ids may contain at most 200 values"), 400

    try:
        ids = [int(item) for item in listing_ids]
    except (TypeError, ValueError):
        return jsonify(error="listing_ids must contain integers"), 400

    existing = db.execute(
        f"SELECT id, status FROM listings WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    ).fetchall()
    existing_ids = {row["id"] for row in existing}
    missing = [listing_id for listing_id in ids if listing_id not in existing_ids]
    if missing:
        return jsonify(error="Some listings were not found", missing_ids=missing), 404

    for listing_id in ids:
        db.execute("DELETE FROM listing_images WHERE listing_id = ?", (listing_id,))
        db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))

    _refresh_listing_city_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:listings-by-city:")
    if any(row["status"] == "published" for row in existing):
        apply_public_listing_side_effects(db)
    return jsonify(ok=True, deleted=len(ids))


@admin_bp.route("/export/csv", methods=["GET"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_export_csv():
    from app import get_db

    db = get_db()
    params = []
    query = """
        SELECT id, title, city, district, property_type, condition_type,
               price, rooms, area, floor, total_floors, year_built, e_oselya,
               status, description, latitude, longitude, images, created_at
        FROM listings
    """

    try:
        clauses, params = build_listing_filters(request.args, allow_ids=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY created_at DESC"
    rows = db.execute(query, params).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "id", "title", "city", "district", "property_type", "condition_type",
        "price", "rooms", "area", "floor", "total_floors", "year_built",
        "e_oselya", "status", "description", "latitude", "longitude", "images",
        "created_at"
    ])
    for row in rows:
        writer.writerow([
            row["id"],
            row["title"],
            row["city"],
            row["district"],
            row["property_type"],
            row["condition_type"],
            row["price"],
            row["rooms"],
            row["area"],
            row["floor"],
            row["total_floors"],
            row["year_built"],
            row["e_oselya"],
            row["status"],
            row["description"],
            row["latitude"],
            row["longitude"],
            row["images"],
            row["created_at"],
        ])

    filename = "ua-homes-listings.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


# ─── Image Management ────────────────────────────────────────────────

@admin_bp.route("/listings/<int:listing_id>/images", methods=["POST"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_upload_image(listing_id):
    """Upload image for listing"""
    from app import get_db
    from werkzeug.utils import secure_filename
    import os
    
    db = get_db()
    
    if not db.execute("SELECT id FROM listings WHERE id = ?", (listing_id,)).fetchone():
        return jsonify(error="Listing not found"), 404
    
    if 'image' not in request.files:
        return jsonify(error="No image provided"), 400
    
    file = request.files['image']
    
    if not file.filename:
        return jsonify(error="Empty filename"), 400
    
    # Validate file type
    allowed_ext = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower()
    
    if ext not in allowed_ext:
        return jsonify(error=f"File type not allowed. Allowed: {allowed_ext}"), 400
    
    # Create directory if needed
    img_dir = f'web/images/listings/{listing_id}'
    os.makedirs(img_dir, exist_ok=True)
    
    # Save file
    filename = secure_filename(file.filename)
    timestamp = str(int(__import__('time').time()))
    filename = f"{timestamp}_{filename}"
    filepath = os.path.join(img_dir, filename)
    
    file.save(filepath)
    
    # Save to DB
    image_url = f"/images/listings/{listing_id}/{filename}"
    
    db.execute(LISTING_IMAGE_INSERT_SQL, (listing_id, image_url, 0))
    current_images_row = db.execute(
        "SELECT images FROM listings WHERE id = ?",
        (listing_id,)
    ).fetchone()
    current_images = []
    try:
        current_images = json.loads(current_images_row["images"] or "[]") if current_images_row else []
        if not isinstance(current_images, list):
            current_images = []
    except json.JSONDecodeError:
        current_images = []
    current_images.append(image_url)
    db.execute(
        "UPDATE listings SET images = ? WHERE id = ?",
        (json.dumps(current_images[:10]), listing_id)
    )
    db.commit()
    
    image_id = db.execute(
        "SELECT id FROM listing_images WHERE listing_id = ? AND image_url = ?",
        (listing_id, image_url)
    ).fetchone()[0]
    
    return jsonify(
        ok=True,
        id=image_id,
        url=image_url
    ), 201


@admin_bp.route("/listings/<int:listing_id>/images/<int:image_id>", methods=["DELETE"])
@require_permission(Permission.LISTINGS_WRITE)
def admin_delete_image(listing_id, image_id):
    """Delete image"""
    from app import get_db
    import os
    
    db = get_db()
    
    image = db.execute(
        "SELECT image_url FROM listing_images WHERE id = ? AND listing_id = ?",
        (image_id, listing_id)
    ).fetchone()
    
    if not image:
        return jsonify(error="Image not found"), 404
    
    # Delete file
    filepath = image['image_url'].lstrip('/')
    if os.path.exists(filepath):
        os.remove(filepath)
    
    # Delete DB record
    db.execute("DELETE FROM listing_images WHERE id = ?", (image_id,))
    current_images_row = db.execute(
        "SELECT images FROM listings WHERE id = ?",
        (listing_id,)
    ).fetchone()
    if current_images_row:
        try:
            current_images = json.loads(current_images_row["images"] or "[]")
        except json.JSONDecodeError:
            current_images = []
        if isinstance(current_images, list):
            current_images = [url for url in current_images if url != image["image_url"]]
            db.execute(
                "UPDATE listings SET images = ? WHERE id = ?",
                (json.dumps(current_images[:10]), listing_id)
            )
    db.commit()
    
    return jsonify(ok=True)


# ─── User Management ────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@require_permission(Permission.USERS_MANAGE)
def admin_get_users():
    """Get all users"""
    from app import get_db
    
    db = get_db()
    args = request.args
    
    role = (args.get("role") or "").strip().lower()
    search = (args.get("search") or "").strip()
    if role and role not in {"user", "agent", "admin", "moderator"}:
        return jsonify(error="Invalid role filter"), 400
    if len(search) > 120:
        return jsonify(error="search must be at most 120 characters"), 400
    try:
        limit, offset = parse_pagination(args)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    
    query = "SELECT id, name, email, role, status, created_at FROM users WHERE 1=1"
    params = []
    
    if role:
        query += " AND role = ?"
        params.append(role)
    if search:
        query += " AND (name LIKE ? OR email LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term])

    total_query = "SELECT COUNT(*) FROM (" + query + ") filtered_users"
    total = db.execute(total_query, params).fetchone()[0]
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = db.execute(query, params).fetchall()
    
    return jsonify(
        users=[dict(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset
    )


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@require_permission(Permission.USERS_MANAGE)
def admin_update_user(user_id):
    """Update user role/status"""
    from app import get_db
    
    db = get_db()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    
    if 'role' not in data and 'status' not in data:
        return jsonify(error="No updates provided"), 400

    allowed_roles = {'user', 'agent', 'admin', 'moderator'}
    allowed_statuses = {'active', 'inactive', 'suspended'}
    role = str(data.get('role') or '').strip().lower() if 'role' in data else None
    status = str(data.get('status') or '').strip().lower() if 'status' in data else None
    if role is not None and role not in allowed_roles:
        return jsonify(error=f"Invalid role. Allowed: {sorted(allowed_roles)}"), 400
    if status is not None and status not in allowed_statuses:
        return jsonify(error=f"Invalid status. Allowed: {sorted(allowed_statuses)}"), 400

    existing = db.execute(
        "SELECT id, role, status FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not existing:
        return jsonify(error="User not found"), 404

    resulting_role = role if role is not None else existing["role"]
    resulting_status = status if status is not None else existing["status"]
    removes_admin_access = (
        existing["role"] == StaffRole.ADMIN.value
        and (
            resulting_role != StaffRole.ADMIN.value
            or resulting_status != "active"
        )
    )
    if existing["id"] == g.user_id and (
        resulting_role != StaffRole.ADMIN.value or resulting_status != "active"
    ):
        return jsonify(error="You cannot remove your own admin access"), 409
    if removes_admin_access:
        if getattr(db, "_is_postgres", False):
            active_admins = len(
                db.execute(
                    """
                    SELECT id FROM users
                    WHERE role = 'admin' AND status = 'active'
                    ORDER BY id
                    FOR UPDATE
                    """
                ).fetchall()
            )
        else:
            active_admins = db.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()[0]
        if int(active_admins or 0) <= 1:
            return jsonify(error="At least one active admin is required"), 409

    updates = []
    params = []
    if role is not None and role != existing['role']:
        updates.append("role = ?")
        params.append(role)
    if status is not None and status != existing['status']:
        updates.append("status = ?")
        params.append(status)
    if not updates:
        db.rollback()
        return jsonify(ok=True)

    updates.append("auth_token_version = auth_token_version + 1")
    params.append(user_id)
    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    
    db.execute(query, params)
    db.commit()
    
    return jsonify(ok=True)


# ─── Staff operations contracts ──────────────────────────────────────

REPORT_STATUSES = {"pending", "reviewing", "resolved", "dismissed"}
REPORT_TRANSITIONS = {
    "pending": {"pending", "reviewing", "resolved", "dismissed"},
    "reviewing": {"reviewing", "resolved", "dismissed"},
    "resolved": {"resolved"},
    "dismissed": {"dismissed"},
}
LEAD_STATUSES = {"new", "viewed", "responded", "closed"}
LEAD_TRANSITIONS = {
    "new": LEAD_STATUSES,
    "viewed": {"viewed", "responded", "closed"},
    "responded": {"responded", "closed"},
    "closed": {"closed"},
}
VERIFICATION_STATUSES = {"unverified", "pending", "verified", "rejected"}


def _serialize_listing_report(row):
    return {
        "id": int(row["id"]),
        "listing_id": int(row["listing_id"]),
        "listing_title": row["listing_title"],
        "reason_code": row["reason_code"],
        "details": row["details"] or "",
        "status": row["status"],
        "created_at": row["created_at"],
    }


@admin_bp.route("/reports/listings", methods=["GET"])
@admin_bp.route("/listing-reports", methods=["GET"])
@require_permission(Permission.REPORTS_MANAGE)
def admin_listing_reports():
    from app import get_db

    try:
        limit, offset = parse_pagination(request.args, max_limit=100)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    status = (request.args.get("status") or "").strip().lower()
    search = (request.args.get("search") or "").strip()
    if status and status not in REPORT_STATUSES:
        return jsonify(error="Invalid report status"), 400
    if len(search) > 120:
        return jsonify(error="search must be at most 120 characters"), 400
    clauses, params = [], []
    if status:
        clauses.append("lr.status = ?")
        params.append(status)
    if search:
        clauses.append("(l.title LIKE ? OR lr.reason_code LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    db = get_db()
    total = db.execute(
        f"SELECT COUNT(*) FROM listing_reports lr JOIN listings l ON l.id = lr.listing_id{where}",
        params,
    ).fetchone()[0]
    rows = db.execute(
        f"""
        SELECT lr.id, lr.listing_id, l.title AS listing_title, lr.reason_code,
               lr.details, lr.status, lr.created_at
        FROM listing_reports lr
        JOIN listings l ON l.id = lr.listing_id
        {where}
        ORDER BY CASE lr.status WHEN 'pending' THEN 0 WHEN 'reviewing' THEN 1 ELSE 2 END,
                 lr.created_at ASC, lr.id ASC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return jsonify(
        reports=[_serialize_listing_report(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@admin_bp.route("/reports/listings/<int:report_id>", methods=["GET"])
@admin_bp.route("/listing-reports/<int:report_id>", methods=["GET"])
@require_permission(Permission.REPORTS_MANAGE)
def admin_listing_report_detail(report_id):
    from app import get_db

    row = get_db().execute(
        """
        SELECT lr.id, lr.listing_id, l.title AS listing_title, lr.reason_code,
               lr.details, lr.status, lr.created_at
        FROM listing_reports lr
        JOIN listings l ON l.id = lr.listing_id
        WHERE lr.id = ?
        """,
        (report_id,),
    ).fetchone()
    if not row:
        return jsonify(error="Report not found"), 404
    return jsonify(report=_serialize_listing_report(row))


@admin_bp.route("/reports/listings/<int:report_id>", methods=["PATCH"])
@admin_bp.route("/listing-reports/<int:report_id>", methods=["PATCH"])
@require_permission(Permission.REPORTS_MANAGE)
def admin_update_listing_report(report_id):
    from app import get_db

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    status = str(data.get("status") or "").strip().lower()
    if status not in REPORT_STATUSES:
        return jsonify(error="Invalid report status"), 400
    db = get_db()
    existing = db.execute(
        "SELECT status FROM listing_reports WHERE id = ?", (report_id,)
    ).fetchone()
    if not existing:
        return jsonify(error="Report not found"), 404
    if status not in REPORT_TRANSITIONS.get(existing["status"], set()):
        return jsonify(error="Invalid report status transition"), 409
    transition = db.execute(
        "UPDATE listing_reports SET status = ? WHERE id = ? AND status = ?",
        (status, report_id, existing["status"]),
    )
    if transition.rowcount != 1:
        db.rollback()
        return jsonify(error="Report status changed; refresh and try again"), 409
    db.commit()
    return jsonify(ok=True, status=status)


@admin_bp.route("/verifications", methods=["GET"])
@require_permission(Permission.VERIFICATIONS_MANAGE)
def admin_verification_queue():
    from app import get_db

    try:
        limit, offset = parse_pagination(request.args, max_limit=100)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    status = (request.args.get("status") or "pending").strip().lower()
    if status not in VERIFICATION_STATUSES:
        return jsonify(error="Invalid verification status"), 400
    params = [status, status, status]
    where = """
        WHERE listing_verification_status = ?
           OR owner_verification_status = ?
           OR phone_verification_status = ?
    """
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM listings {where}", params).fetchone()[0]
    rows = db.execute(
        f"""
        SELECT id, title, city, status, listing_verification_status,
               owner_verification_status, phone_verification_status, created_at
        FROM listings {where}
        ORDER BY created_at ASC, id ASC LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    return jsonify(
        verifications=[dict(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@admin_bp.route("/verifications/<int:listing_id>", methods=["PATCH"])
@require_permission(Permission.VERIFICATIONS_MANAGE)
def admin_update_verification(listing_id):
    from app import (
        cache_delete_prefix,
        get_db,
        log_field_change,
        log_listing_event,
    )

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    fields = {
        "listing_verification_status": "listing_verification_status",
        "owner_verification_status": "owner_verification_status",
        "phone_verification_status": "phone_verification_status",
    }
    supplied = {key: str(data[key]).strip().lower() for key in fields if key in data}
    if not supplied:
        return jsonify(error="No verification status provided"), 400
    if any(value not in VERIFICATION_STATUSES for value in supplied.values()):
        return jsonify(error="Invalid verification status"), 400
    db = get_db()
    listing = db.execute(
        """
        SELECT id, listing_verification_status, owner_verification_status,
               phone_verification_status
        FROM listings WHERE id = ?
        """,
        (listing_id,),
    ).fetchone()
    if not listing:
        return jsonify(error="Listing not found"), 404
    updates, params = [], []
    for field, value in supplied.items():
        updates.append(f"{field} = ?")
        params.append(value)
        if field == "listing_verification_status":
            log_field_change(db, listing_id, field, listing[field], value, "admin")
    if "owner_verification_status" in supplied:
        updates.append("verified_owner = ?")
        params.append(int(supplied["owner_verification_status"] == "verified"))
    if "phone_verification_status" in supplied:
        updates.append("verified_phone = ?")
        params.append(int(supplied["phone_verification_status"] == "verified"))
    params.append(listing_id)
    db.execute(f"UPDATE listings SET {', '.join(updates)} WHERE id = ?", params)
    log_listing_event(db, listing_id, "verification_updated", admin_id=g.user_id)
    db.commit()
    cache_delete_prefix("public:listings:")
    return jsonify(ok=True, listing_id=listing_id, **supplied)


def _serialize_admin_lead(row):
    return {
        "id": int(row["id"]),
        "lead_type": row["lead_type"],
        "source": row["source"],
        "name": row["name"],
        "phone": row["phone"],
        "email": row["email"],
        "preferred_channel": row["preferred_channel"] or "phone",
        "listing_id": row["listing_id"],
        "listing_title": row["listing_title"],
        "city": row["city"],
        "district": row["district"],
        "message": row["message"] or "",
        "status": row["status"] or "new",
        "response_message": row["response_message"] or "",
        "responded_at": row["responded_at"],
        "created_at": row["created_at"],
    }


def _admin_lead_select():
    return """
        SELECT lr.id, lr.lead_type, lr.source, lr.name, lr.phone, lr.email,
               lr.preferred_channel, lr.listing_id, l.title AS listing_title,
               lr.city, lr.district, lr.message, lr.status,
               lr.response_message, lr.responded_at, lr.created_at
        FROM lead_requests lr
        LEFT JOIN listings l ON l.id = lr.listing_id
    """


@admin_bp.route("/leads", methods=["GET"])
@require_permission(Permission.LEADS_MANAGE)
def admin_leads():
    from app import get_db

    try:
        limit, offset = parse_pagination(request.args, max_limit=100)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    status = (request.args.get("status") or "").strip().lower()
    search = (request.args.get("search") or "").strip()
    if status and status not in LEAD_STATUSES:
        return jsonify(error="Invalid lead status"), 400
    if len(search) > 120:
        return jsonify(error="search must be at most 120 characters"), 400
    clauses, params = [], []
    if status:
        clauses.append("lr.status = ?")
        params.append(status)
    if search:
        clauses.append("(lr.name LIKE ? OR lr.email LIKE ? OR lr.phone LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM lead_requests lr{where}", params).fetchone()[0]
    rows = db.execute(
        _admin_lead_select() + where
        + " ORDER BY lr.created_at DESC, lr.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return jsonify(
        leads=[_serialize_admin_lead(row) for row in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@admin_bp.route("/leads/<int:lead_id>", methods=["GET"])
@require_permission(Permission.LEADS_MANAGE)
def admin_lead_detail(lead_id):
    from app import get_db

    row = get_db().execute(
        _admin_lead_select() + " WHERE lr.id = ?", (lead_id,)
    ).fetchone()
    if not row:
        return jsonify(error="Lead not found"), 404
    return jsonify(lead=_serialize_admin_lead(row))


@admin_bp.route("/leads/<int:lead_id>", methods=["PATCH"])
@require_permission(Permission.LEADS_MANAGE)
def admin_update_lead(lead_id):
    from app import cache_delete_prefix, get_db

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="JSON object required"), 400
    status = str(data.get("status") or "").strip().lower()
    response_message = str(data.get("response_message") or "").strip()[:1200]
    if status not in LEAD_STATUSES:
        return jsonify(error="Invalid lead status"), 400
    db = get_db()
    row = db.execute(
        "SELECT status FROM lead_requests WHERE id = ?", (lead_id,)
    ).fetchone()
    if not row:
        return jsonify(error="Lead not found"), 404
    current_status = row["status"] or "new"
    if status not in LEAD_TRANSITIONS.get(current_status, set()):
        return jsonify(error="Invalid lead status transition"), 409
    if status == "responded" and not response_message:
        return jsonify(error="response_message is required when responding"), 400
    responded_at = (
        datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
        if status == "responded" else None
    )
    transition = db.execute(
        """
        UPDATE lead_requests
        SET status = ?, response_message = CASE WHEN ? = '' THEN response_message ELSE ? END,
            responded_at = COALESCE(?, responded_at)
        WHERE id = ? AND COALESCE(status, 'new') = ?
        """,
        (
            status,
            response_message,
            response_message,
            responded_at,
            lead_id,
            current_status,
        ),
    )
    if transition.rowcount != 1:
        db.rollback()
        return jsonify(error="Lead status changed; refresh and try again"), 409
    db.commit()
    cache_delete_prefix("admin:reports:lead-funnel:")
    return jsonify(ok=True, status=status, responded_at=responded_at)


ORGANIZATION_STATUSES = {"active", "suspended"}


def _admin_organizations(kind):
    from app import _agency_metrics, get_db

    try:
        limit, offset = parse_pagination(request.args, default_limit=30, max_limit=100)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    search = (request.args.get("search") or "").strip()
    status = (request.args.get("status") or "").strip().lower()
    verified = (request.args.get("verified") or "").strip().lower()
    if len(search) > 120:
        return jsonify(error="search must be at most 120 characters"), 400
    if status and status not in ORGANIZATION_STATUSES:
        return jsonify(error="Invalid organization status"), 400
    if verified and verified not in {"true", "false"}:
        return jsonify(error="verified must be true or false"), 400
    clauses = ["ap.kind = ?"]
    params = [kind]
    if search:
        clauses.append(
            "(LOWER(ap.name) LIKE LOWER(?) OR LOWER(ap.slug) LIKE LOWER(?)"
            " OR LOWER(ap.city) LIKE LOWER(?))"
        )
        params.extend([f"%{search}%"] * 3)
    if status:
        clauses.append("ap.status = ?")
        params.append(status)
    if verified:
        clauses.append("ap.is_verified = ?")
        params.append(int(verified == "true"))
    where = "WHERE " + " AND ".join(clauses)
    db = get_db()
    total = db.execute(
        "SELECT COUNT(*) FROM agency_profiles ap " + where,
        tuple(params),
    ).fetchone()[0]
    agencies = _agency_metrics(
        db,
        where_sql=where,
        where_params=tuple(params),
        limit=limit + offset,
        include_management=True,
    )[offset:offset + limit]
    key = "developers" if kind == "developer" else "agencies"
    return jsonify(**{key: agencies}, total=int(total), limit=limit, offset=offset)


def _admin_organization_detail(slug, kind):
    from app import _agency_metrics, get_db

    rows = _agency_metrics(
        get_db(),
        where_sql="WHERE ap.slug = ? AND ap.kind = ?",
        where_params=(slug, kind),
        limit=1,
        include_management=True,
    )
    if not rows:
        return jsonify(error="Organization not found"), 404
    key = "developer" if kind == "developer" else "agency"
    return jsonify(**{key: rows[0]})


def _validate_organization_payload(data, *, creating=False):
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    values = {}
    if creating or "slug" in data:
        slug = str(data.get("slug") or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 80:
            raise ValueError("Invalid organization slug")
        values["slug"] = slug
    for field, maximum in (("name", 160), ("city", 120), ("specialization", 500)):
        if creating or field in data:
            value = str(data.get(field) or "").strip()
            if (field != "specialization" and not value) or len(value) > maximum:
                raise ValueError(f"Invalid {field}")
            values[field] = value
    if creating or "kind" in data:
        kind = str(data.get("kind") or "agency").strip().lower()
        if kind not in {"agency", "developer"}:
            raise ValueError("kind must be agency or developer")
        values["kind"] = kind
    if "status" in data:
        status = str(data.get("status") or "").strip().lower()
        if status not in ORGANIZATION_STATUSES:
            raise ValueError("status must be active or suspended")
        values["status"] = status
    for field in ("avg_response_minutes", "team_size", "completed_deals"):
        if field in data:
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be an integer")
            if value < 0 or value > 1_000_000:
                raise ValueError(f"Invalid {field}")
            values[field] = value
    return values


def _expected_revision(data):
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    revision = data.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise ValueError("revision must be a positive integer")
    if revision < 1:
        raise ValueError("revision must be a positive integer")
    return revision


def _admin_create_organization(kind):
    from app import _is_db_unique_error, get_db

    try:
        values = _validate_organization_payload(
            request.get_json(silent=True), creating=True
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    values["kind"] = kind
    values["status"] = "active"
    db = get_db()
    if db.execute("SELECT 1 FROM agency_profiles WHERE slug = ?", (values["slug"],)).fetchone():
        return jsonify(error="Organization slug already exists"), 409
    try:
        cursor = db.execute(
            """
            INSERT INTO agency_profiles (
                slug, name, kind, city, specialization, status,
                avg_response_minutes, team_size, completed_deals
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["slug"], values["name"], kind, values["city"],
                values["specialization"], values["status"],
                values.get("avg_response_minutes"), values.get("team_size"),
                values.get("completed_deals", 0),
            ),
        )
    except Exception as exc:
        if not _is_db_unique_error(exc):
            raise
        db.rollback()
        return jsonify(error="Organization slug already exists"), 409
    db.commit()
    return jsonify(
        ok=True, id=cursor.lastrowid, slug=values["slug"], revision=1
    ), 201


def _admin_update_organization(slug, kind):
    from app import db_now_expr, get_db

    data = request.get_json(silent=True)
    try:
        revision = _expected_revision(data)
        values = _validate_organization_payload(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    values.pop("slug", None)
    values.pop("kind", None)
    if not values:
        return jsonify(error="No organization fields provided"), 400
    db = get_db()
    existing = db.execute(
        """
        SELECT status, is_verified, revision
        FROM agency_profiles WHERE slug = ? AND kind = ?
        """,
        (slug, kind),
    ).fetchone()
    if not existing:
        return jsonify(error="Organization not found"), 404
    if int(existing["revision"]) != revision:
        return jsonify(error="Organization changed; refresh and try again"), 409
    assignments = [f"{key} = ?" for key in values]
    params = list(values.values())
    if values.get("status") == "suspended":
        assignments.extend(["is_verified = 0", "last_verified_at = NULL"])
    assignments.extend([
        f"updated_at = {db_now_expr()}",
        "revision = revision + 1",
    ])
    transition = db.execute(
        f"""
        UPDATE agency_profiles
        SET {', '.join(assignments)}
        WHERE slug = ? AND kind = ? AND revision = ?
        """,
        params + [slug, kind, revision],
    )
    if transition.rowcount != 1:
        db.rollback()
        return jsonify(error="Organization changed; refresh and try again"), 409
    db.commit()
    return jsonify(ok=True, slug=slug, revision=revision + 1)


def _admin_verify_organization(slug, kind):
    from app import db_now_expr, get_db

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("verified"), bool):
        return jsonify(error="verified must be a boolean"), 400
    try:
        revision = _expected_revision(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    existing = db.execute(
        """
        SELECT status, revision FROM agency_profiles
        WHERE slug = ? AND kind = ?
        """,
        (slug, kind),
    ).fetchone()
    if not existing:
        return jsonify(error="Organization not found"), 404
    if int(existing["revision"]) != revision:
        return jsonify(error="Organization changed; refresh and try again"), 409
    if data["verified"] and existing["status"] != "active":
        return jsonify(error="Suspended organizations cannot be verified"), 409
    transition = db.execute(
        f"""
        UPDATE agency_profiles
        SET is_verified = ?,
            last_verified_at = CASE WHEN ? = 1 THEN {db_now_expr()} ELSE NULL END,
            updated_at = {db_now_expr()},
            revision = revision + 1
        WHERE slug = ? AND kind = ? AND revision = ?
        """,
        (
            int(data["verified"]), int(data["verified"]), slug, kind, revision,
        ),
    )
    if transition.rowcount != 1:
        db.rollback()
        return jsonify(error="Organization changed; refresh and try again"), 409
    db.commit()
    return jsonify(
        ok=True, slug=slug, is_verified=data["verified"], revision=revision + 1
    )


def _admin_delete_organization(slug, kind):
    from app import get_db

    data = request.get_json(silent=True)
    try:
        revision = _expected_revision(data)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    db = get_db()
    existing = db.execute(
        """
        SELECT status, is_verified, revision
        FROM agency_profiles WHERE slug = ? AND kind = ?
        """,
        (slug, kind),
    ).fetchone()
    if not existing:
        return jsonify(error="Organization not found"), 404
    if int(existing["revision"]) != revision:
        return jsonify(error="Organization changed; refresh and try again"), 409
    if existing["status"] != "suspended" or bool(existing["is_verified"]):
        return jsonify(
            error="Suspend and remove verification before deleting"
        ), 409
    user_count = db.execute(
        "SELECT COUNT(*) FROM users WHERE agency_slug = ?", (slug,)
    ).fetchone()[0]
    listing_count = db.execute(
        "SELECT COUNT(*) FROM listings WHERE agency_slug = ?", (slug,)
    ).fetchone()[0]
    if int(user_count) or int(listing_count):
        return jsonify(
            error="Organization is linked to users or listings and cannot be deleted"
        ), 409
    deleted = db.execute(
        """
        DELETE FROM agency_profiles
        WHERE slug = ? AND kind = ? AND revision = ?
          AND NOT EXISTS (
              SELECT 1 FROM users WHERE agency_slug = ?
          )
          AND NOT EXISTS (
              SELECT 1 FROM listings WHERE agency_slug = ?
          )
        """,
        (slug, kind, revision, slug, slug),
    )
    if deleted.rowcount != 1:
        db.rollback()
        return jsonify(error="Organization changed; refresh and try again"), 409
    db.commit()
    return jsonify(ok=True, slug=slug)


@admin_bp.route("/agencies", methods=["GET"])
@require_permission(Permission.AGENCIES_MANAGE)
def admin_agencies():
    return _admin_organizations("agency")


@admin_bp.route("/agencies/<string:slug>", methods=["GET"])
@require_permission(Permission.AGENCIES_MANAGE)
def admin_agency_detail(slug):
    return _admin_organization_detail(slug, "agency")


@admin_bp.route("/agencies", methods=["POST"])
@require_permission(Permission.AGENCIES_MANAGE)
def admin_create_agency():
    return _admin_create_organization("agency")


@admin_bp.route("/agencies/<string:slug>", methods=["PATCH"])
@require_permission(Permission.AGENCIES_MANAGE)
def admin_update_agency(slug):
    return _admin_update_organization(slug, "agency")


@admin_bp.route("/agencies/<string:slug>/verify", methods=["POST"])
@require_permission(Permission.AGENCIES_MANAGE)
def admin_verify_agency(slug):
    return _admin_verify_organization(slug, "agency")


@admin_bp.route("/agencies/<string:slug>", methods=["DELETE"])
@require_permission(Permission.AGENCIES_MANAGE)
def admin_delete_agency(slug):
    return _admin_delete_organization(slug, "agency")


@admin_bp.route("/developers", methods=["GET"])
@require_permission(Permission.DEVELOPERS_MANAGE)
def admin_developers():
    return _admin_organizations("developer")


@admin_bp.route("/developers/<string:slug>", methods=["GET"])
@require_permission(Permission.DEVELOPERS_MANAGE)
def admin_developer_detail(slug):
    return _admin_organization_detail(slug, "developer")


@admin_bp.route("/developers", methods=["POST"])
@require_permission(Permission.DEVELOPERS_MANAGE)
def admin_create_developer():
    return _admin_create_organization("developer")


@admin_bp.route("/developers/<string:slug>", methods=["PATCH"])
@require_permission(Permission.DEVELOPERS_MANAGE)
def admin_update_developer(slug):
    return _admin_update_organization(slug, "developer")


@admin_bp.route("/developers/<string:slug>/verify", methods=["POST"])
@require_permission(Permission.DEVELOPERS_MANAGE)
def admin_verify_developer(slug):
    return _admin_verify_organization(slug, "developer")


@admin_bp.route("/developers/<string:slug>", methods=["DELETE"])
@require_permission(Permission.DEVELOPERS_MANAGE)
def admin_delete_developer(slug):
    return _admin_delete_organization(slug, "developer")


@admin_bp.route("/listings/<int:listing_id>/history", methods=["GET"])
@require_permission(Permission.LISTINGS_READ)
def admin_listing_history(listing_id):
    from app import get_db, public_field_history

    try:
        limit, offset = parse_pagination(request.args, default_limit=50, max_limit=50)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if offset:
        return jsonify(error="offset is not supported for listing history"), 400
    db = get_db()
    if not db.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone():
        return jsonify(error="Listing not found"), 404
    history = public_field_history(db, listing_id, limit)
    return jsonify(
        listing_id=listing_id,
        history=history,
        price_history=[row for row in history if row["field_name"] == "price"],
    )


@admin_bp.route("/audit", methods=["GET"])
@require_permission(Permission.AUDIT_READ)
def admin_audit():
    from app import get_db

    try:
        limit, offset = parse_pagination(request.args, max_limit=100)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    clauses, params = [], []
    for argument, column in (
        ("actor_id", "aal.actor_id"),
        ("action", "aal.action"),
        ("permission", "aal.permission"),
        ("resource_type", "aal.resource_type"),
        ("resource_id", "aal.resource_id"),
    ):
        value = (request.args.get(argument) or "").strip()
        if value:
            if len(value) > 120:
                return jsonify(error=f"{argument} is too long"), 400
            if argument == "actor_id":
                try:
                    value = int(value)
                except ValueError:
                    return jsonify(error="actor_id must be an integer"), 400
            clauses.append(f"{column} = ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM admin_audit_log aal{where}", params).fetchone()[0]
    rows = db.execute(
        f"""
        SELECT aal.id, aal.actor_id, aal.actor_role, u.name AS actor_name,
               aal.action, aal.permission, aal.resource_type, aal.resource_id,
               aal.metadata_json, aal.request_id, aal.created_at
        FROM admin_audit_log aal
        LEFT JOIN users u ON u.id = aal.actor_id
        {where}
        ORDER BY aal.created_at DESC, aal.id DESC LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    entries = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        entries.append(item)
    return jsonify(audit=entries, total=int(total), limit=limit, offset=offset)


@admin_bp.route("/system/health", methods=["GET"])
@require_permission(Permission.SYSTEM_READ)
def admin_system_health():
    from app import get_db

    db = get_db()
    db.execute("SELECT 1").fetchone()
    return jsonify(
        status="ok",
        database="ok",
        counts={
            "users": int(db.execute("SELECT COUNT(*) FROM users").fetchone()[0]),
            "listings": int(db.execute("SELECT COUNT(*) FROM listings").fetchone()[0]),
            "pending_reports": int(db.execute(
                "SELECT COUNT(*) FROM listing_reports WHERE status = 'pending'"
            ).fetchone()[0]),
        },
        request_id=getattr(g, "request_id", None),
    )


# ─── Reports ────────────────────────────────────────────────────────

@admin_bp.route("/reports/listings-by-city", methods=["GET"])
@require_auth_admin
def admin_report_listings_by_city():
    """Get listings count by city"""
    from app import cached_json_get, cached_json_set, get_db

    cache_key = "admin:reports:listings-by-city:v1"
    cached = cached_json_get(cache_key)
    if cached is not None:
        return jsonify(data=cached)
    
    db = get_db()
    
    rows = db.execute("""
        SELECT city, published_count AS count, avg_price
        FROM listing_city_summary
        ORDER BY published_count DESC, city ASC
    """).fetchall()
    data = [dict(row) for row in rows]
    cached_json_set(cache_key, data, 60)
    return jsonify(data=data)


@admin_bp.route("/reports/user-growth", methods=["GET"])
@require_auth_admin
def admin_report_user_growth():
    """Get user growth over time"""
    from app import cached_json_get, cached_json_set, get_db

    cache_key = "admin:reports:user-growth:v1"
    cached = cached_json_get(cache_key)
    if cached is not None:
        return jsonify(data=cached)
    
    db = get_db()
    
    rows = db.execute(
        """
        SELECT day AS date, user_count AS count
        FROM user_growth_daily
        WHERE day >= ?
        ORDER BY day ASC
        """,
        (_cutoff_date(30),),
    ).fetchall()
    data = [dict(row) for row in rows]
    cached_json_set(cache_key, data, 300)
    return jsonify(data=data)


def _to_ctr(submits: int, intents: int) -> float:
    if intents <= 0:
        return 0.0
    return round((submits / intents) * 100, 2)


def _build_observability_report(db, hours: int):
    from app import cached_json_get, cached_json_set

    hours = max(1, min(int(hours), 168))
    cache_key = f"admin:reports:observability:{hours}:v1"
    cached = cached_json_get(cache_key)
    if cached is not None:
        return cached

    window_cutoff = _cutoff_datetime(hours)
    summary_rows = db.execute(
        """
        SELECT event_type, COUNT(*) AS count
        FROM client_observability_events
        WHERE created_at >= ?
        GROUP BY event_type
        """,
        (window_cutoff,),
    ).fetchall()
    summary_map = {row["event_type"]: int(row["count"] or 0) for row in summary_rows}

    recent_error_rows = db.execute(
        """
        SELECT id, event_type, message, source, page_url, created_at
        FROM client_observability_events
        WHERE created_at >= ?
          AND event_type IN ('runtime_error', 'unhandled_rejection')
        ORDER BY created_at DESC
        LIMIT 12
        """,
        (window_cutoff,),
    ).fetchall()

    vitals_rows = db.execute(
        """
        SELECT
            metric_name,
            COUNT(*) AS samples,
            ROUND(AVG(metric_value), 2) AS avg_value,
            SUM(CASE WHEN rating = 'good' THEN 1 ELSE 0 END) AS good_count,
            SUM(CASE WHEN rating = 'needs-improvement' THEN 1 ELSE 0 END) AS needs_improvement_count,
            SUM(CASE WHEN rating = 'poor' THEN 1 ELSE 0 END) AS poor_count
        FROM client_observability_events
        WHERE created_at >= ?
          AND event_type = 'web_vital'
          AND metric_name IS NOT NULL
        GROUP BY metric_name
        ORDER BY metric_name ASC
        """,
        (window_cutoff,),
    ).fetchall()

    recent_vitals_rows = db.execute(
        """
        SELECT metric_name, metric_value, rating, source, page_url, created_at
        FROM client_observability_events
        WHERE created_at >= ?
          AND event_type = 'web_vital'
        ORDER BY created_at DESC
        LIMIT 15
        """,
        (window_cutoff,),
    ).fetchall()

    report = {
        "window_hours": hours,
        "summary": {
            "events_total": int(sum(summary_map.values())),
            "runtime_error": int(summary_map.get("runtime_error", 0)),
            "unhandled_rejection": int(summary_map.get("unhandled_rejection", 0)),
            "web_vital": int(summary_map.get("web_vital", 0)),
        },
        "recent_errors": [dict(row) for row in recent_error_rows],
        "vitals_by_metric": [dict(row) for row in vitals_rows],
        "recent_vitals": [dict(row) for row in recent_vitals_rows],
    }
    cached_json_set(cache_key, report, 60)
    return report


@admin_bp.route("/reports/observability", methods=["GET"])
@require_auth_admin
def admin_report_observability():
    from app import get_db

    db = get_db()
    hours = request.args.get("hours", "24")
    try:
        hours_int = int(hours)
    except ValueError:
        return jsonify(error="hours must be integer"), 400
    if hours_int < 1 or hours_int > 168:
        return jsonify(error="hours must be between 1 and 168"), 400
    return jsonify(_build_observability_report(db, hours_int))


def _build_lead_funnel_report(db, days_int: int):
    from app import cached_json_get, cached_json_set

    cache_key = f"admin:reports:lead-funnel:{days_int}:v3"
    cached = cached_json_get(cache_key)
    if cached is not None:
        return cached

    window_cutoff = _cutoff_date(days_int)
    prev_window_cutoff = _cutoff_date(days_int * 2)

    source_rows = db.execute(
        """
        SELECT source,
               SUM(CASE WHEN event = 'lead_intent' THEN event_count ELSE 0 END) AS intents,
               SUM(CASE WHEN event = 'lead_submit' THEN event_count ELSE 0 END) AS submits,
               SUM(CASE WHEN event = 'lead_redirect' THEN event_count ELSE 0 END) AS redirects,
               SUM(CASE WHEN event = 'detail_view' THEN event_count ELSE 0 END) AS views
        FROM lead_funnel_daily_metrics
        WHERE day >= ?
        GROUP BY source
        ORDER BY intents DESC, submits DESC
        """,
        (window_cutoff,),
    ).fetchall()

    listing_type_rows = db.execute(
        """
        SELECT listing_type,
               SUM(CASE WHEN event = 'lead_intent' THEN event_count ELSE 0 END) AS intents,
               SUM(CASE WHEN event = 'lead_submit' THEN event_count ELSE 0 END) AS submits,
               SUM(CASE WHEN event = 'lead_redirect' THEN event_count ELSE 0 END) AS redirects,
               SUM(CASE WHEN event = 'detail_view' THEN event_count ELSE 0 END) AS views
        FROM lead_funnel_daily_metrics
        WHERE day >= ?
        GROUP BY listing_type
        ORDER BY intents DESC, submits DESC
        """,
        (window_cutoff,),
    ).fetchall()

    popular_route_rows = db.execute(
        """
        SELECT
            source,
            SUM(route_applies) AS route_applies,
            COUNT(*) AS sessions,
            SUM(CASE WHEN submit_at IS NOT NULL AND submit_at >= first_route_at THEN 1 ELSE 0 END) AS submit_sessions
        FROM lead_funnel_session_rollups
        WHERE first_route_at >= ?
        GROUP BY source
        ORDER BY route_applies DESC, submit_sessions DESC, source ASC
        """,
        (window_cutoff,),
    ).fetchall()

    daily_rows = db.execute(
        """
        SELECT day,
               SUM(CASE WHEN event = 'lead_intent' THEN event_count ELSE 0 END) AS intents,
               SUM(CASE WHEN event = 'lead_submit' THEN event_count ELSE 0 END) AS submits
        FROM lead_funnel_daily_metrics
        WHERE day >= ?
        GROUP BY day
        ORDER BY day ASC
        """,
        (window_cutoff,),
    ).fetchall()

    top_listing_rows = db.execute(
        """
        SELECT
            lfm.listing_id,
            COALESCE(l.title, 'Listing #' || lfm.listing_id) AS title,
            SUM(CASE WHEN lfm.event = 'detail_view' THEN lfm.event_count ELSE 0 END) AS views,
            SUM(CASE WHEN lfm.event = 'lead_intent' THEN lfm.event_count ELSE 0 END) AS intents,
            SUM(CASE WHEN lfm.event = 'lead_submit' THEN lfm.event_count ELSE 0 END) AS submits,
            SUM(CASE WHEN lfm.event = 'lead_redirect' THEN lfm.event_count ELSE 0 END) AS redirects
        FROM lead_funnel_listing_metrics lfm
        LEFT JOIN listings l ON l.id = lfm.listing_id
        WHERE lfm.day >= ?
        GROUP BY lfm.listing_id
        HAVING intents > 0 OR submits > 0 OR redirects > 0
        ORDER BY submits DESC, intents DESC, redirects DESC
        LIMIT 8
        """,
        (window_cutoff,),
    ).fetchall()

    current_row = db.execute(
        """
        SELECT
            SUM(CASE WHEN event = 'detail_view' THEN event_count ELSE 0 END) AS views,
            SUM(CASE WHEN event = 'lead_intent' THEN event_count ELSE 0 END) AS intents,
            SUM(CASE WHEN event = 'lead_submit' THEN event_count ELSE 0 END) AS submits,
            SUM(CASE WHEN event = 'lead_redirect' THEN event_count ELSE 0 END) AS redirects
        FROM lead_funnel_daily_metrics
        WHERE day >= ?
        """,
        (window_cutoff,),
    ).fetchone()

    previous_row = db.execute(
        """
        SELECT
            SUM(CASE WHEN event = 'detail_view' THEN event_count ELSE 0 END) AS views,
            SUM(CASE WHEN event = 'lead_intent' THEN event_count ELSE 0 END) AS intents,
            SUM(CASE WHEN event = 'lead_submit' THEN event_count ELSE 0 END) AS submits,
            SUM(CASE WHEN event = 'lead_redirect' THEN event_count ELSE 0 END) AS redirects
        FROM lead_funnel_daily_metrics
        WHERE day >= ?
          AND day < ?
        """,
        (prev_window_cutoff, window_cutoff),
    ).fetchone()

    current_totals = {
        "views": int(current_row["views"] or 0),
        "intents": int(current_row["intents"] or 0),
        "submits": int(current_row["submits"] or 0),
        "redirects": int(current_row["redirects"] or 0),
    }
    current_totals["ctr_intent_to_submit"] = _to_ctr(current_totals["submits"], current_totals["intents"])

    previous_totals = {
        "views": int(previous_row["views"] or 0),
        "intents": int(previous_row["intents"] or 0),
        "submits": int(previous_row["submits"] or 0),
        "redirects": int(previous_row["redirects"] or 0),
    }
    previous_totals["ctr_intent_to_submit"] = _to_ctr(previous_totals["submits"], previous_totals["intents"])

    by_source = []
    for row in source_rows:
        intents = int(row["intents"] or 0)
        submits = int(row["submits"] or 0)
        redirects = int(row["redirects"] or 0)
        views = int(row["views"] or 0)
        by_source.append(
            {
                "source": row["source"] or "unknown",
                "views": views,
                "intents": intents,
                "submits": submits,
                "redirects": redirects,
                "ctr_intent_to_submit": _to_ctr(submits, intents),
            }
        )

    by_listing_type = []
    for row in listing_type_rows:
        intents = int(row["intents"] or 0)
        submits = int(row["submits"] or 0)
        redirects = int(row["redirects"] or 0)
        views = int(row["views"] or 0)
        by_listing_type.append(
            {
                "listing_type": row["listing_type"],
                "views": views,
                "intents": intents,
                "submits": submits,
                "redirects": redirects,
                "ctr_intent_to_submit": _to_ctr(submits, intents),
            }
        )

    by_popular_route = []
    for row in popular_route_rows:
        route_applies = int(row["route_applies"] or 0)
        sessions = int(row["sessions"] or 0)
        submit_sessions = int(row["submit_sessions"] or 0)
        by_popular_route.append(
            {
                "source": row["source"] or "popular_route:unknown",
                "route_applies": route_applies,
                "sessions": sessions,
                "submit_sessions": submit_sessions,
                "ctr_route_to_submit": _to_ctr(submit_sessions, sessions),
            }
        )

    daily_trend = []
    for row in daily_rows:
        intents = int(row["intents"] or 0)
        submits = int(row["submits"] or 0)
        daily_trend.append(
            {
                "day": row["day"],
                "intents": intents,
                "submits": submits,
                "ctr_intent_to_submit": _to_ctr(submits, intents),
            }
        )

    top_listings = []
    for row in top_listing_rows:
        intents = int(row["intents"] or 0)
        submits = int(row["submits"] or 0)
        redirects = int(row["redirects"] or 0)
        views = int(row["views"] or 0)
        top_listings.append(
            {
                "listing_id": int(row["listing_id"]),
                "title": row["title"],
                "views": views,
                "intents": intents,
                "submits": submits,
                "redirects": redirects,
                "ctr_intent_to_submit": _to_ctr(submits, intents),
            }
        )

    report = {
        "window_days": days_int,
        "totals": current_totals,
        "comparison": {
            "previous_window_days": days_int,
            "previous_totals": previous_totals,
            "delta": {
                "views": current_totals["views"] - previous_totals["views"],
                "intents": current_totals["intents"] - previous_totals["intents"],
                "submits": current_totals["submits"] - previous_totals["submits"],
                "redirects": current_totals["redirects"] - previous_totals["redirects"],
                "ctr_intent_to_submit": round(
                    current_totals["ctr_intent_to_submit"] - previous_totals["ctr_intent_to_submit"],
                    2,
                ),
            },
        },
        "by_source": by_source,
        "by_listing_type": by_listing_type,
        "by_popular_route": by_popular_route,
        "daily_trend": daily_trend,
        "top_listings": top_listings,
    }
    cached_json_set(cache_key, report, 120)
    return report


@admin_bp.route("/reports/lead-funnel", methods=["GET"])
@require_auth_admin
def admin_report_lead_funnel():
    from app import get_db

    db = get_db()
    days = request.args.get("days", "30")
    try:
        days_int = int(days)
    except ValueError:
        return jsonify(error="days must be integer"), 400
    if days_int < 1 or days_int > 180:
        return jsonify(error="days must be between 1 and 180"), 400
    return jsonify(_build_lead_funnel_report(db, days_int))


@admin_bp.route("/reports/lead-funnel/export.csv", methods=["GET"])
@require_auth_admin
def admin_report_lead_funnel_csv():
    from app import get_db

    db = get_db()
    days = request.args.get("days", "30")
    try:
        days_int = int(days)
    except ValueError:
        return jsonify(error="days must be integer"), 400
    if days_int < 1 or days_int > 180:
        return jsonify(error="days must be between 1 and 180"), 400

    report = _build_lead_funnel_report(db, days_int)
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["section", "metric", "value", "previous", "delta"])
    totals = report["totals"]
    prev = report["comparison"]["previous_totals"]
    delta = report["comparison"]["delta"]
    writer.writerow(["totals", "views", totals["views"], prev["views"], delta["views"]])
    writer.writerow(["totals", "intents", totals["intents"], prev["intents"], delta["intents"]])
    writer.writerow(["totals", "submits", totals["submits"], prev["submits"], delta["submits"]])
    writer.writerow(["totals", "redirects", totals["redirects"], prev["redirects"], delta["redirects"]])
    writer.writerow(["totals", "ctr_intent_to_submit", totals["ctr_intent_to_submit"], prev["ctr_intent_to_submit"], delta["ctr_intent_to_submit"]])

    writer.writerow([])
    writer.writerow(["by_source", "source", "intents", "submits", "ctr_intent_to_submit"])
    for row in report["by_source"]:
        writer.writerow(["by_source", row["source"], row["intents"], row["submits"], row["ctr_intent_to_submit"]])

    writer.writerow([])
    writer.writerow(["by_listing_type", "listing_type", "intents", "submits", "ctr_intent_to_submit"])
    for row in report["by_listing_type"]:
        writer.writerow(["by_listing_type", row["listing_type"], row["intents"], row["submits"], row["ctr_intent_to_submit"]])

    writer.writerow([])
    writer.writerow(["by_popular_route", "source", "route_applies", "sessions", "submit_sessions", "ctr_route_to_submit"])
    for row in report.get("by_popular_route", []):
        writer.writerow([
            "by_popular_route",
            row["source"],
            row["route_applies"],
            row["sessions"],
            row["submit_sessions"],
            row["ctr_route_to_submit"],
        ])

    writer.writerow([])
    writer.writerow(["top_listings", "listing_id", "title", "intents", "submits", "ctr_intent_to_submit"])
    for row in report["top_listings"]:
        writer.writerow(["top_listings", row["listing_id"], row["title"], row["intents"], row["submits"], row["ctr_intent_to_submit"]])

    filename = f"ua-homes-lead-funnel-{days_int}d.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
