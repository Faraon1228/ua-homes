"""
UA Homes Admin API Routes
Endpoints for admin panel property/user management
"""

from flask import Blueprint, g, jsonify, request, Response
from functools import wraps
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
    from app import get_db
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
    db.commit()
    
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
               created_at, views, e_oselya
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
    from app import get_db
    
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
    
    db.execute("""
        INSERT INTO listings 
        (title, city, district, property_type, condition_type, price, rooms, area,
         floor, total_floors, year_built, e_oselya, description, status, user_id,
         latitude, longitude)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        data.get('status', 'draft'),
        g.user_id,  # Admin as owner
        data.get('latitude'),
        data.get('longitude')
    ))
    db.commit()
    
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
                  property_type, condition_type, latitude, longitude, views,
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
    from app import get_db
    
    db = get_db()
    data = request.get_json() or {}
    
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
        'latitude', 'longitude', 'status'
    ]
    
    for field in allowed_fields:
        if field in data:
            updates.append(f"{field} = ?")
            params.append(data[field])
    
    if not updates:
        return jsonify(error="No fields to update"), 400
    
    params.append(listing_id)
    query = f"UPDATE listings SET {', '.join(updates)} WHERE id = ?"
    
    db.execute(query, params)
    db.commit()
    
    return jsonify(ok=True, id=listing_id)


@admin_bp.route("/listings/<int:listing_id>", methods=["DELETE"])
@require_auth_admin
def admin_delete_listing(listing_id):
    """Delete listing"""
    from app import get_db
    
    db = get_db()
    
    if not db.execute("SELECT id FROM listings WHERE id = ?", (listing_id,)).fetchone():
        return jsonify(error="Listing not found"), 404
    
    # Delete images first
    db.execute("DELETE FROM listing_images WHERE listing_id = ?", (listing_id,))
    
    # Delete listing
    db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    db.commit()
    
    return jsonify(ok=True)


@admin_bp.route("/listings/<int:listing_id>/duplicate", methods=["POST"])
@require_auth_admin
def admin_duplicate_listing(listing_id):
    from app import get_db
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
    return jsonify(ok=True, id=new_listing_id, title=title), 201


@admin_bp.route("/listings/<int:listing_id>/publish", methods=["POST"])
@require_auth_admin
def admin_publish_listing(listing_id):
    """Publish/unpublish listing"""
    from app import get_db
    
    db = get_db()
    data = request.get_json() or {}
    published = data.get('published', True)
    
    status = 'published' if published else 'draft'
    
    db.execute(
        """
        UPDATE listings
        SET status = ?,
            moderation_status = ?,
            moderation_updated_at = datetime('now'),
            published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, datetime('now')) ELSE published_at END
        WHERE id = ?
        """,
        (status, "approved" if published else "pending_review", status, listing_id)
    )
    log_moderation_action(db, listing_id, "publish" if published else "unpublish")
    db.commit()
    
    return jsonify(ok=True, status=status)


@admin_bp.route("/import/csv", methods=["POST"])
@require_auth_admin
def admin_import_csv():
    from app import get_db

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
            """
            INSERT INTO listings (
                user_id, title, city, district, property_type, condition_type,
                price, rooms, area, floor, total_floors, year_built, e_oselya,
                views, images, status, latitude, longitude, description,
                moderation_status, moderation_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
    from app import get_db

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
        """
        UPDATE listings
        SET status = ?,
            moderation_status = ?,
            moderation_reason = ?,
            moderation_updated_at = datetime('now'),
            published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, datetime('now')) ELSE published_at END,
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
    from app import get_db

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
            """
            UPDATE listings
            SET status = ?,
                moderation_status = ?,
                moderation_reason = ?,
                moderation_updated_at = datetime('now'),
                published_at = CASE WHEN ? = 'published' THEN COALESCE(published_at, datetime('now')) ELSE published_at END
            WHERE id = ?
            """,
            (new_status, moderation_status, reason, new_status, listing_id)
        )
        log_moderation_action(db, listing_id, action, reason)

    db.commit()
    return jsonify(ok=True, status=new_status, moderation_status=moderation_status, updated=len(ids))


@admin_bp.route("/listings/bulk-delete", methods=["POST"])
@require_auth_admin
def admin_bulk_delete():
    from app import get_db

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
    from app import get_db
    
    db = get_db()
    
    rows = db.execute("""
        SELECT city, COUNT(*) as count, ROUND(AVG(price)) as avg_price
        FROM listings WHERE status = 'published'
        GROUP BY city ORDER BY count DESC
    """).fetchall()
    
    return jsonify(data=[dict(row) for row in rows])


@admin_bp.route("/reports/user-growth", methods=["GET"])
@require_auth_admin
def admin_report_user_growth():
    """Get user growth over time"""
    from app import get_db
    
    db = get_db()
    
    rows = db.execute("""
        SELECT DATE(created_at) as date, COUNT(*) as count
        FROM users
        GROUP BY DATE(created_at)
        ORDER BY date DESC
        LIMIT 30
    """).fetchall()
    
    return jsonify(data=[dict(row) for row in rows])
