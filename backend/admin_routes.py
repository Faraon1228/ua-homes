"""
UA Homes Admin API Routes
Endpoints for admin panel property/user management
"""

from flask import Blueprint, g, jsonify, request, Response
from functools import wraps
import datetime
import csv
import io
import json

# Create blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Helper: Require JWT auth + admin role
def require_auth_admin(f):
    """Require both auth and admin role"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Check auth
        from app import decode_token
        import jwt
        
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Unauthorized"), 401
        
        token = auth[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify(error="Token expired"), 401
        except jwt.PyJWTError:
            return jsonify(error="Invalid token"), 401
        
        g.user_id = int(payload["sub"])
        g.user_email = payload["email"]
        
        # Check admin role
        from app import get_db
        db = get_db()
        user = db.execute(
            "SELECT role FROM users WHERE id = ?",
            (g.user_id,)
        ).fetchone()
        
        if not user or user['role'] != 'admin':
            return jsonify(error="Admin access required"), 403
        
        return f(*args, **kwargs)
    return wrapper


def log_moderation_action(db, listing_id, action, reason=None):
    db.execute(
        "INSERT INTO moderation_log (listing_id, admin_id, action, reason) VALUES (?, ?, ?, ?)",
        (listing_id, g.user_id, action, reason)
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


def parse_csv_row(row, row_number):
    required = ["title", "city", "district", "price", "rooms", "area"]
    missing = [field for field in required if not str(row.get(field, "")).strip()]
    if missing:
        return None, f"Row {row_number}: missing required fields: {', '.join(missing)}"

    try:
        price = int(float(row.get("price")))
        rooms = int(float(row.get("rooms")))
        area = float(row.get("area"))
        floor = int(float(row.get("floor", 1) or 1))
        total_floors = int(float(row.get("total_floors", 1) or 1))
        year_built = row.get("year_built")
        year_built = int(float(year_built)) if str(year_built).strip() else None
        latitude = row.get("latitude")
        latitude = float(latitude) if str(latitude).strip() else None
        longitude = row.get("longitude")
        longitude = float(longitude) if str(longitude).strip() else None
    except ValueError as exc:
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
            clauses.append(f"id IN ({','.join('?' for _ in ids)})")
            params.extend(ids)

    city = (args.get("city") or "").strip()
    status = (args.get("status") or "").strip()
    search = (args.get("search") or "").strip()

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
    
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    name = (data.get('name') or 'Admin').strip()
    
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
        (name, email, password, hashed, 'admin', 'active')
    )
    _refresh_user_growth_summary(db)
    db.commit()
    cache_delete_prefix("admin:reports:user-growth:")
    
    return jsonify(
        ok=True,
        message="Admin account created. Please login."
    ), 201


@admin_bp.route("/auth/login", methods=["POST"])
def admin_login():
    """Admin login — returns JWT token"""
    from app import get_db, make_token
    import bcrypt
    
    db = get_db()
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    
    if not email or not password:
        return jsonify(error="Email and password required"), 400
    
    user = db.execute(
        "SELECT id, password_hash, role FROM users WHERE email = ?",
        (email,)
    ).fetchone()
    
    if not user:
        return jsonify(error="User not found"), 404
    
    if user['role'] != 'admin':
        return jsonify(error="User is not an admin"), 403
    
    # Check password
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        return jsonify(error="Invalid password"), 401
    
    # Generate token
    token = make_token(user['id'], email)
    
    return jsonify(
        ok=True,
        token=token,
        user_id=user['id']
    )


# ─── Admin Dashboard ─────────────────────────────────────────────────

@admin_bp.route("/dashboard/stats", methods=["GET"])
@require_auth_admin
def dashboard_stats():
    """Get dashboard statistics"""
    from app import get_db
    
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
    
    return jsonify(
        total_listings=total_listings,
        published_listings=published_listings,
        total_users=total_users,
        total_agents=total_agents,
        avg_price=int(avg_price),
        by_city=[dict(row) for row in by_city],
        recent_listings=[dict(row) for row in recent]
    )


# ─── Admin Listings Management ──────────────────────────────────────────

@admin_bp.route("/listings", methods=["GET"])
@require_auth_admin
def admin_get_listings():
    """Get all listings with filters for admin"""
    from app import get_db
    
    db = get_db()
    args = request.args
    
    limit = min(int(args.get('limit', 50)), 200)
    offset = max(int(args.get('offset', 0)), 0)
    
    query = """
        SELECT id, title, city, district, price, rooms, area, status, 
               created_at, views, e_oselya, images, listing_highlights, capture_mode,
               property_type, condition_type, listing_status, source, has_photo_tour, has_video_tour
        FROM listings WHERE 1=1
    """
    clauses, params = build_listing_filters(args)
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
@require_auth_admin
def admin_create_listing():
    """Create new listing as admin"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db
    
    db = get_db()
    data = request.get_json() or {}
    
    required = ['title', 'city', 'district', 'price', 'rooms', 'area']
    if not all(k in data for k in required):
        return jsonify(error=f"Missing required fields: {required}"), 400
    
    try:
        price = int(data['price'])
        rooms = int(data['rooms'])
        area = float(data['area'])
    except (ValueError, TypeError):
        return jsonify(error="Price/rooms/area must be numbers"), 400
    
    status = str(data.get('status') or 'draft').strip().lower()
    if status not in {'draft', 'published', 'pending', 'rejected', 'archived'}:
        status = 'draft'
    listing_status = str(data.get('listing_status') or data.get('listingStatus') or 'active').strip().lower()
    if listing_status not in {'active', 'sold', 'removed'}:
        listing_status = 'active'
    now = datetime.datetime.utcnow().isoformat(timespec='seconds')

    db.execute("""
        INSERT INTO listings 
        (title, city, district, property_type, condition_type, price, rooms, area,
        floor, total_floors, year_built, e_oselya, description, status, listing_status, moderation_status, moderation_updated_at, published_at, user_id,
        latitude, longitude, source, has_photo_tour, has_video_tour, listing_highlights, capture_mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    
    listing_id = db.execute(
        "SELECT id FROM listings ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    
    return jsonify(id=listing_id, ok=True), 201


@admin_bp.route("/listings/<int:listing_id>", methods=["GET"])
@require_auth_admin
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
        "SELECT id, image_url FROM listing_images WHERE listing_id = ? ORDER BY 'order'",
        (listing_id,)
    ).fetchall()
    
    result = dict(listing)
    result['images'] = [dict(img) for img in images]
    
    return jsonify(listing=result)


@admin_bp.route("/listings/<int:listing_id>", methods=["PUT"])
@require_auth_admin
def admin_update_listing(listing_id):
    """Update listing"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db
    
    db = get_db()
    data = request.get_json() or {}
    now = datetime.datetime.utcnow().isoformat(timespec='seconds')
    
    # Check listing exists
    if not db.execute("SELECT id FROM listings WHERE id = ?", (listing_id,)).fetchone():
        return jsonify(error="Listing not found"), 404
    
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
            elif field == 'listing_highlights' and isinstance(value, list):
                value = json.dumps(value, ensure_ascii=False)
            elif field in {'capture_mode', 'source', 'status', 'listing_status', 'property_type', 'condition_type'} and value is not None:
                value = str(value).strip()
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
    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    
    return jsonify(ok=True, id=listing_id)


@admin_bp.route("/listings/<int:listing_id>", methods=["DELETE"])
@require_auth_admin
def admin_delete_listing(listing_id):
    """Delete listing"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db
    
    db = get_db()
    
    if not db.execute("SELECT id FROM listings WHERE id = ?", (listing_id,)).fetchone():
        return jsonify(error="Listing not found"), 404
    
    # Delete images first
    db.execute("DELETE FROM listing_images WHERE listing_id = ?", (listing_id,))
    
    # Delete listing
    db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    
    return jsonify(ok=True)


@admin_bp.route("/listings/<int:listing_id>/duplicate", methods=["POST"])
@require_auth_admin
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
        db.execute(
            "INSERT INTO listing_images (listing_id, image_url, 'order') VALUES (?, ?, ?)",
            row
        )

    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    return jsonify(ok=True, id=new_listing_id, title=title), 201


@admin_bp.route("/listings/<int:listing_id>/publish", methods=["POST"])
@require_auth_admin
def admin_publish_listing(listing_id):
    """Publish/unpublish listing"""
    from app import _refresh_listing_city_summary, cache_delete_prefix, db_now_expr, get_db
    
    db = get_db()
    data = request.get_json() or {}
    published = data.get('published', True)
    
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
    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    
    return jsonify(ok=True, status=status)


@admin_bp.route("/import/csv", methods=["POST"])
@require_auth_admin
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

    if errors:
        db.rollback()
        return jsonify(error="CSV import failed", details=errors[:20]), 422

    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    return jsonify(ok=True, imported=len(imported), listing_ids=imported), 201


@admin_bp.route("/moderation/queue", methods=["GET"])
@require_auth_admin
def admin_moderation_queue():
    from app import get_db

    db = get_db()
    rows = db.execute(
        """
        SELECT id, title, city, district, price, rooms, area, status, created_at,
               moderation_status, moderation_reason,
               owner_verification_status, phone_verification_status
        FROM listings
        WHERE status IN ('draft', 'pending', 'rejected')
           OR moderation_status IN ('in_review', 'changes_requested')
           OR owner_verification_status = 'pending'
           OR phone_verification_status = 'pending'
        ORDER BY
            CASE
                WHEN owner_verification_status = 'pending' OR phone_verification_status = 'pending' THEN 0
                WHEN moderation_status IN ('changes_requested', 'in_review') THEN 1
                WHEN status IN ('pending', 'draft') THEN 2
                WHEN status = 'rejected' THEN 3
                ELSE 4
            END,
            created_at ASC
        """
    ).fetchall()
    return jsonify(queue=[dict(row) for row in rows])


@admin_bp.route("/moderation/logs", methods=["GET"])
@require_auth_admin
def admin_moderation_logs():
    from app import get_db

    db = get_db()
    rows = db.execute(
        """
        SELECT ml.id, ml.listing_id, ml.action, ml.reason, ml.created_at,
               l.title, l.city,
               u.name AS admin_name
        FROM moderation_log ml
        JOIN listings l ON l.id = ml.listing_id
        LEFT JOIN users u ON u.id = ml.admin_id
        ORDER BY ml.created_at DESC
        LIMIT 50
        """
    ).fetchall()
    return jsonify(logs=[dict(row) for row in rows])


@admin_bp.route("/listings/<int:listing_id>/moderate", methods=["POST"])
@require_auth_admin
def admin_moderate_listing(listing_id):
    from app import _refresh_listing_city_summary, cache_delete_prefix, db_now_expr, get_db

    db = get_db()
    data = request.get_json() or {}
    action = (data.get("action") or "").strip().lower()
    reason = (data.get("reason") or "").strip() or None
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
    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")

    return jsonify(
        ok=True,
        status=new_status,
        moderation_status=moderation_status,
        owner_verification_status=next_owner_verification_status,
        phone_verification_status=next_phone_verification_status,
    )


@admin_bp.route("/listings/bulk-moderate", methods=["POST"])
@require_auth_admin
def admin_bulk_moderate():
    from app import _refresh_listing_city_summary, cache_delete_prefix, db_now_expr, get_db

    db = get_db()
    data = request.get_json() or {}
    action = (data.get("action") or "").strip().lower()
    reason = (data.get("reason") or "").strip() or None
    listing_ids = data.get("listing_ids") or []

    if not isinstance(listing_ids, list) or not listing_ids:
        return jsonify(error="listing_ids must be a non-empty array"), 400

    try:
        ids = [int(item) for item in listing_ids]
    except (TypeError, ValueError):
        return jsonify(error="listing_ids must contain integers"), 400

    moderation_status = moderation_state_for_action(action)
    if not moderation_status:
        return jsonify(error="Invalid moderation action"), 400
    new_status = listing_status_for_moderation(moderation_status)

    existing = db.execute(
        f"SELECT id FROM listings WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    ).fetchall()
    existing_ids = {row["id"] for row in existing}
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

    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    return jsonify(ok=True, status=new_status, moderation_status=moderation_status, updated=len(ids))


@admin_bp.route("/listings/bulk-delete", methods=["POST"])
@require_auth_admin
def admin_bulk_delete():
    from app import _refresh_listing_city_summary, cache_delete_prefix, get_db

    db = get_db()
    data = request.get_json() or {}
    listing_ids = data.get("listing_ids") or []

    if not isinstance(listing_ids, list) or not listing_ids:
        return jsonify(error="listing_ids must be a non-empty array"), 400

    try:
        ids = [int(item) for item in listing_ids]
    except (TypeError, ValueError):
        return jsonify(error="listing_ids must contain integers"), 400

    existing = db.execute(
        f"SELECT id FROM listings WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    ).fetchall()
    existing_ids = {row["id"] for row in existing}
    missing = [listing_id for listing_id in ids if listing_id not in existing_ids]
    if missing:
        return jsonify(error="Some listings were not found", missing_ids=missing), 404

    for listing_id in ids:
        db.execute("DELETE FROM listing_images WHERE listing_id = ?", (listing_id,))
        db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))

    db.commit()
    _refresh_listing_city_summary(db)
    cache_delete_prefix("admin:reports:listings-by-city:")
    return jsonify(ok=True, deleted=len(ids))


@admin_bp.route("/export/csv", methods=["GET"])
@require_auth_admin
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
@require_auth_admin
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
    
    db.execute(
        "INSERT INTO listing_images (listing_id, image_url, 'order') VALUES (?, ?, ?)",
        (listing_id, image_url, 0)
    )
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
@require_auth_admin
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
@require_auth_admin
def admin_get_users():
    """Get all users"""
    from app import get_db
    
    db = get_db()
    args = request.args
    
    role = (args.get('role') or '').strip()
    limit = min(int(args.get('limit', 50)), 200)
    offset = max(int(args.get('offset', 0)), 0)
    
    query = "SELECT id, name, email, role, status, created_at FROM users WHERE 1=1"
    params = []
    
    if role:
        query += " AND role = ?"
        params.append(role)
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = db.execute(query, params).fetchall()
    
    return jsonify(
        users=[dict(row) for row in rows],
        limit=limit,
        offset=offset
    )


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@require_auth_admin
def admin_update_user(user_id):
    """Update user role/status"""
    from app import get_db
    
    db = get_db()
    data = request.get_json() or {}
    
    updates = []
    params = []
    
    if 'role' in data:
        updates.append("role = ?")
        params.append(data['role'])
    
    if 'status' in data:
        updates.append("status = ?")
        params.append(data['status'])
    
    if not updates:
        return jsonify(error="No updates provided"), 400
    
    params.append(user_id)
    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    
    db.execute(query, params)
    db.commit()
    
    return jsonify(ok=True)


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
    days_int = max(1, min(days_int, 180))
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
    days_int = max(1, min(days_int, 180))

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
