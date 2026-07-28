"""
UA Homes Admin API Routes
Endpoints for admin panel property/user management
"""

from flask import Blueprint, g, jsonify, request
import json

# Create blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# Helper: Check if user is admin
def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(g, 'user_id') or g.user_id is None:
            return jsonify(error="Unauthorized"), 401
        
        db = g.get('db')
        if not db:
            return jsonify(error="Database error"), 500
            
        user = db.execute(
            "SELECT role FROM users WHERE id = ?",
            (g.user_id,)
        ).fetchone()
        
        if not user or user['role'] != 'admin':
            return jsonify(error="Forbidden - admin access required"), 403
        
        return f(*args, **kwargs)
    return decorated_function


# ─── Admin Auth ──────────────────────────────────────────────────────────

@admin_bp.route("/auth/register", methods=["POST"])
def admin_register():
    """Register new admin (first admin only)"""
    from app import get_db
    import bcrypt
    
    db = get_db()
    
    # Check if any admin exists (first admin bypass)
    existing_admin = db.execute(
        "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
    ).fetchone()
    
    if existing_admin and request.remote_addr not in ['127.0.0.1', 'localhost']:
        return jsonify(error="Admin already exists. Contact existing admin."), 403
    
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
        "INSERT INTO users (name, email, password_hash, role, status) VALUES (?, ?, ?, ?, ?)",
        (name, email, hashed, 'admin', 'active')
    )
    db.commit()
    
    return jsonify(
        ok=True,
        message="Admin account created. Please login."
    ), 201


# ─── Admin Dashboard ─────────────────────────────────────────────────────

@admin_bp.route("/dashboard/stats", methods=["GET"])
@require_admin
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
@require_admin
def admin_get_listings():
    """Get all listings with filters for admin"""
    from app import get_db
    
    db = get_db()
    args = request.args
    
    city = (args.get('city') or '').strip()
    status = (args.get('status') or '').strip()
    search = (args.get('search') or '').strip()
    limit = min(int(args.get('limit', 50)), 200)
    offset = max(int(args.get('offset', 0)), 0)
    
    query = """
        SELECT id, title, city, district, price, rooms, area, status, 
               created_at, views, e_oselya
        FROM listings WHERE 1=1
    """
    params = []
    
    if city:
        query += " AND city = ?"
        params.append(city)
    if status:
        query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (title LIKE ? OR district LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    rows = db.execute(query, params).fetchall()
    
    total = db.execute(
        "SELECT COUNT(*) FROM listings WHERE 1=1" +
        (" AND city = ?" if city else "") +
        (" AND status = ?" if status else "") +
        (" AND (title LIKE ? OR district LIKE ?)" if search else ""),
        params[:-2] if len(params) > 2 else params
    ).fetchone()[0]
    
    return jsonify(
        listings=[dict(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset
    )


@admin_bp.route("/listings", methods=["POST"])
@require_admin
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
        data.get('floor'),
        data.get('total_floors'),
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
@require_admin
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
@require_admin
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
@require_admin
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


@admin_bp.route("/listings/<int:listing_id>/publish", methods=["POST"])
@require_admin
def admin_publish_listing(listing_id):
    """Publish/unpublish listing"""
    from app import get_db
    
    db = get_db()
    data = request.get_json() or {}
    published = data.get('published', True)
    
    status = 'published' if published else 'draft'
    
    db.execute(
        "UPDATE listings SET status = ? WHERE id = ?",
        (status, listing_id)
    )
    db.commit()
    
    return jsonify(ok=True, status=status)


# ─── Image Management ────────────────────────────────────────────────────

@admin_bp.route("/listings/<int:listing_id>/images", methods=["POST"])
@require_admin
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
@require_admin
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


# ─── User Management ────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
@require_admin
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
@require_admin
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


# ─── Reports ────────────────────────────────────────────────────────────

@admin_bp.route("/reports/listings-by-city", methods=["GET"])
@require_admin
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
@require_admin
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
