from __future__ import annotations
"""UA Homes backend — Flask + SQLite.
Security: bcrypt passwords, JWT auth, rate limiting, CORS, parameterised queries.
"""
import json
import os
import re
import sqlite3
import secrets
import datetime
from functools import wraps

import bcrypt
import jwt
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ─── Config ──────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "ua_homes.db")

SECRET_KEY = os.environ.get("UA_HOMES_SECRET", secrets.token_hex(32))
JWT_ALGO   = "HS256"
JWT_EXP_H  = 72

# ─── App setup ───────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["300 per minute"],
    storage_uri="memory://",
)

# ─── Database ────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ─── Seed data ────────────────────────────────────────────────────────────────

IMG = "https://images.unsplash.com/photo-{id}?auto=format&fit=crop&w=900&q=80"
def imgs(*ids): return json.dumps([IMG.format(id=i) for i in ids])

SEED_LISTINGS = [
    # (title, city, district, property_type, condition_type, price, rooms, area,
    #  floor, total_floors, year_built, e_oselya, images_json, description, lat, lng)
    ("Сучасна 2-кімнатна, ЖК 'Грінвіль'", "Київ", "Печерський",
     "квартира", "нова будова", 125000, 2, 68.0, 8, 24, 2021, 1,
     imgs("1560185007-c5ca9d2c014d","1502672260266-1c1ef2d93688","1493809842364-78817add7ffb"),
     "Сучасна квартира з панорамним виглядом на Дніпро. Оздоблення «комфорт плюс», підземний паркінг, консьєрж.",
     50.4422, 30.5178),

    ("Видова смарт-квартира біля метро", "Київ", "Голосіївський",
     "квартира", "після ремонту", 48000, 1, 32.0, 5, 16, 2019, 1,
     imgs("1493809842364-78817add7ffb","1484154218962-a197022b5858"),
     "Смарт-квартира з якісним ремонтом, 5 хвилин до метро. Функціональне планування для активного міського життя.",
     50.4122, 30.5122),

    ("Простора 3-к квартира для родини", "Львів", "Франківський",
     "квартира", "вторинка", 95000, 3, 85.0, 3, 9, 2008, 0,
     imgs("1484154218962-a197022b5858","1560185007-c5ca9d2c014d"),
     "Великий сімейний простір у центральному районі Львова. Поруч школа, садочок, парк. Логджія, комора.",
     49.8397, 24.0297),

    ("Затишна 1-кімнатна у новобудові", "Харків", "Слобідський",
     "квартира", "нова будова", 38000, 1, 38.5, 12, 22, 2023, 1,
     imgs("1502672260266-1c1ef2d93688","1560185007-c5ca9d2c014d"),
     "Нова квартира з чистовим оздобленням у ЖК. Закрита територія, дитячий майданчик, відеоспостереження.",
     49.9935, 36.2304),

    ("Великий пентхаус з терасою", "Одеса", "Приморський",
     "квартира", "після ремонту", 210000, 4, 140.0, 16, 16, 2018, 0,
     imgs("1512917774080-9991f1c4c750","1560185007-c5ca9d2c014d","1502672260266-1c1ef2d93688"),
     "Розкішний пентхаус з видом на Чорне море. Велика тераса, авторський дизайн, система розумного дому.",
     46.4825, 30.7233),

    ("Квартира-студія в центрі", "Дніпро", "Центральний",
     "квартира", "після ремонту", 42000, 1, 28.0, 4, 12, 2020, 1,
     imgs("1493809842364-78817add7ffb","1484154218962-a197022b5858"),
     "Сучасна студія у центрі Дніпра. Ідеально для інвестиції або молодих спеціалістів.",
     48.4647, 35.0462),

    ("Приватний будинок з ділянкою", "Київ", "Дарницький",
     "будинок", "після ремонту", 185000, 5, 180.0, 2, 2, 2015, 0,
     imgs("1523217582562-09d0def993a6","1545324418-cc1a3fa10c00","1570129477492-45c003edd2be"),
     "Двоповерховий будинок 8 соток. Підвал, гараж, літня кухня. Тихе місце поруч з транспортом.",
     50.4102, 30.6578),

    ("Офіс у центрі Львова", "Львів", "Галицький",
     "комерція", "після ремонту", 68000, 0, 75.0, 1, 5, 2010, 0,
     imgs("1497366216548-37526070297c","1449844908441-8829872d2607"),
     "Готове офісне приміщення. Окремий вхід, висока стеля 3.2 м, кімната переговорів.",
     49.8429, 24.0322),

    ("2-кімнатна біля парку", "Вінниця", "Замостянський",
     "квартира", "вторинка", 52000, 2, 58.0, 6, 9, 2005, 1,
     imgs("1484154218962-a197022b5858","1502672260266-1c1ef2d93688"),
     "Квартира після капремонту. Балкон з видом на парк, нові вікна та сантехніка.",
     49.2331, 28.4682),

    ("Будинок з садом у передмісті", "Харків", "Жовтневий",
     "будинок", "вторинка", 78000, 4, 120.0, 1, 1, 2000, 0,
     imgs("1570129477492-45c003edd2be","1545324418-cc1a3fa10c00"),
     "Одноповерховий будинок з великим садом. Ідеально для родини з дітьми, тихий район.",
     49.9453, 36.1881),

    ("Стильна 1-кімнатна для інвестиції", "Одеса", "Малиновський",
     "квартира", "нова будова", 35000, 1, 33.0, 7, 18, 2024, 1,
     imgs("1502672260266-1c1ef2d93688","1493809842364-78817add7ffb"),
     "Нова квартира у ЖК бізнес-класу. Розвинена інфраструктура, чудова локація для оренди.",
     46.4456, 30.7134),

    ("4-кімнатна преміум у центрі Києва", "Київ", "Шевченківський",
     "квартира", "після ремонту", 350000, 4, 160.0, 15, 25, 2022, 0,
     imgs("1512917774080-9991f1c4c750","1560185007-c5ca9d2c014d","1484154218962-a197022b5858"),
     "Преміум квартира з дизайнерським ремонтом. Смарт-дім, тепла підлога, консьєрж 24/7.",
     50.4420, 30.5230),
]


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            email           TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password        TEXT    NOT NULL,
            password_hash   TEXT,
            role            TEXT    NOT NULL DEFAULT 'user',
            status          TEXT    NOT NULL DEFAULT 'active',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS listings (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title          TEXT    NOT NULL,
            city           TEXT    NOT NULL,
            district       TEXT    NOT NULL,
            property_type  TEXT    NOT NULL DEFAULT 'квартира',
            condition_type TEXT    NOT NULL DEFAULT 'вторинка',
            price          INTEGER NOT NULL CHECK(price > 0),
            rooms          INTEGER NOT NULL CHECK(rooms >= 0),
            area           REAL    NOT NULL CHECK(area > 0),
            floor          INTEGER NOT NULL DEFAULT 1,
            total_floors   INTEGER NOT NULL DEFAULT 1,
            year_built     INTEGER,
            e_oselya       INTEGER NOT NULL DEFAULT 0,
            views          INTEGER NOT NULL DEFAULT 0,
            images         TEXT    NOT NULL DEFAULT '[]',
            latitude       REAL,
            longitude      REAL,
            description    TEXT    NOT NULL DEFAULT '',
            created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_name  TEXT    NOT NULL,
            rating     INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment    TEXT    NOT NULL,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_listings_city      ON listings(city);
        CREATE INDEX IF NOT EXISTS idx_listings_price     ON listings(price);
        CREATE INDEX IF NOT EXISTS idx_listings_user_id   ON listings(user_id);
        CREATE INDEX IF NOT EXISTS idx_listings_type      ON listings(property_type);
        CREATE INDEX IF NOT EXISTS idx_reviews_listing_id ON reviews(listing_id);
        
        CREATE TABLE IF NOT EXISTS listing_images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            image_url  TEXT    NOT NULL,
            'order'    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        
        CREATE TABLE IF NOT EXISTS moderation_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            admin_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE SET NULL,
            action     TEXT    NOT NULL,
            reason     TEXT,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        
        CREATE INDEX IF NOT EXISTS idx_listing_images ON listing_images(listing_id);
        CREATE INDEX IF NOT EXISTS idx_moderation_log ON moderation_log(listing_id);
    """)
    db.commit()

    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        demo_pw = bcrypt.hashpw(b"demo1234", bcrypt.gensalt(rounds=12)).decode()
        cur = db.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            ("UA Homes Demo", "demo@ua-homes.com", demo_pw),
        )
        demo_id = cur.lastrowid
        db.executemany(
            """INSERT INTO listings
               (user_id,title,city,district,property_type,condition_type,price,rooms,area,
                floor,total_floors,year_built,e_oselya,images,description,latitude,longitude)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(demo_id, *row) for row in SEED_LISTINGS],
        )
        db.commit()

    db.close()


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def make_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=JWT_EXP_H),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGO])


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Токен відсутній або невалідний"), 401
        token = auth[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify(error="Сесія закінчилась — увійдіть знову"), 401
        except jwt.PyJWTError:
            return jsonify(error="Невалідний токен"), 401
        g.user_id    = int(payload["sub"])
        g.user_email = payload["email"]
        return f(*args, **kwargs)
    return wrapper


# ─── Validation helpers ───────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-.]+$")

def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email)) and len(email) <= 254

def strip(val, max_len=255) -> str:
    return str(val or "").strip()[:max_len]

def pos_int(val) -> int | None:
    try:
        v = int(val)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None

def nonneg_int(val) -> int | None:
    try:
        v = int(val)
        return v if v >= 0 else None
    except (TypeError, ValueError):
        return None

def pos_float(val) -> float | None:
    try:
        v = float(val)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _row_to_listing(r) -> dict:
    d = dict(r)
    d["images"] = json.loads(d.get("images") or "[]")
    return d


# ─── Routes: Auth ─────────────────────────────────────────────────────────────

@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per minute")
def register():
    data  = request.get_json(silent=True) or {}
    name  = strip(data.get("name"),  100)
    email = strip(data.get("email"), 254).lower()
    pw    = strip(data.get("password"), 128)

    if not name:
        return jsonify(error="Вкажіть ім'я"), 422
    if not validate_email(email):
        return jsonify(error="Невірний формат email"), 422
    if len(pw) < 8:
        return jsonify(error="Мінімум 8 символів у паролі"), 422

    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
            (name, email, hashed),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error="Цей email вже зареєстровано"), 409

    user_id = cur.lastrowid
    return jsonify(
        token=make_token(user_id, email),
        user={"id": user_id, "name": name, "email": email},
    ), 201


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("20 per minute")
def login():
    data  = request.get_json(silent=True) or {}
    email = strip(data.get("email"), 254).lower()
    pw    = strip(data.get("password"), 128)

    db   = get_db()
    row  = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    dummy_hash = b"$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    candidate  = pw.encode() if row else b""
    stored     = row["password"].encode() if row else dummy_hash

    if not row or not bcrypt.checkpw(candidate, stored):
        return jsonify(error="Невірний email або пароль"), 401

    return jsonify(
        token=make_token(row["id"], row["email"]),
        user={"id": row["id"], "name": row["name"], "email": row["email"]},
    )


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    db  = get_db()
    row = db.execute("SELECT id, name, email FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not row:
        return jsonify(error="Користувача не знайдено"), 404
    return jsonify(user=dict(row))


# ─── Routes: Listings ─────────────────────────────────────────────────────────

ALLOWED_SORT = {
    "price-asc":  "l.price ASC",
    "price-desc": "l.price DESC",
    "area-desc":  "l.area DESC",
    "area-asc":   "l.area ASC",
    "newest":     "l.created_at DESC",
    "views-desc": "l.views DESC",
}

LISTING_SELECT = """
    SELECT l.id, l.title, l.city, l.district, l.property_type, l.condition_type,
           l.price, l.rooms, l.area, l.floor, l.total_floors, l.year_built,
           l.e_oselya, l.views, l.images, l.latitude, l.longitude, l.description,
           l.created_at, u.name AS owner_name, u.email AS owner_email
    FROM   listings l
    JOIN   users u ON u.id = l.user_id
"""


@app.route("/api/listings", methods=["GET"])
def get_listings():
    db   = get_db()
    args = request.args

    city          = strip(args.get("city",      ""), 100)
    prop_type     = strip(args.get("type",      ""), 50)
    min_price     = pos_int(args.get("minPrice"))
    max_price     = pos_int(args.get("maxPrice"))
    min_rooms     = nonneg_int(args.get("minRooms"))
    max_rooms     = nonneg_int(args.get("maxRooms"))
    min_area      = pos_float(args.get("minArea"))
    max_area      = pos_float(args.get("maxArea"))
    e_oselya      = args.get("eOselya") == "1"
    sort_key      = args.get("sort", "newest")
    order_by      = ALLOWED_SORT.get(sort_key, ALLOWED_SORT["newest"])

    query  = LISTING_SELECT + " WHERE 1=1"
    params: list = []

    if city:
        query += " AND l.city = ?"
        params.append(city)
    if prop_type:
        query += " AND l.property_type = ?"
        params.append(prop_type)
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

    query += f" ORDER BY {order_by} LIMIT 200"

    rows = db.execute(query, params).fetchall()
    return jsonify(listings=[_row_to_listing(r) for r in rows])


@app.route("/api/listings/<int:lid>", methods=["GET"])
def get_listing(lid: int):
    db  = get_db()
    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (lid,)).fetchone()
    if not row:
        return jsonify(error="Оголошення не знайдено"), 404
    listing = _row_to_listing(row)
    reviews = db.execute(
        "SELECT id, user_name, rating, comment, created_at FROM reviews WHERE listing_id = ? ORDER BY created_at DESC",
        (lid,)
    ).fetchall()
    listing["reviews"] = [dict(r) for r in reviews]
    return jsonify(listing=listing)


@app.route("/api/listings/<int:lid>/view", methods=["POST"])
def increment_view(lid: int):
    db = get_db()
    db.execute("UPDATE listings SET views = views + 1 WHERE id = ?", (lid,))
    db.commit()
    row = db.execute("SELECT views FROM listings WHERE id = ?", (lid,)).fetchone()
    return jsonify(views=row["views"] if row else 0)


@app.route("/api/listings/<int:lid>/reviews", methods=["GET"])
def get_reviews(lid: int):
    db = get_db()
    rows = db.execute(
        "SELECT id, user_name, rating, comment, created_at FROM reviews WHERE listing_id = ? ORDER BY created_at DESC",
        (lid,)
    ).fetchall()
    return jsonify(reviews=[dict(r) for r in rows])


@app.route("/api/listings/<int:lid>/reviews", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def add_review(lid: int):
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


@app.route("/api/listings", methods=["POST"])
@require_auth
@limiter.limit("30 per hour")
def create_listing():
    data = request.get_json(silent=True) or {}

    title         = strip(data.get("title"),         200)
    city          = strip(data.get("city"),           100)
    district      = strip(data.get("district"),       100)
    prop_type     = strip(data.get("propertyType"),    50) or "квартира"
    condition     = strip(data.get("conditionType"),   50) or "вторинка"
    description   = strip(data.get("description"),   2000)
    price         = pos_int(data.get("price"))
    rooms         = nonneg_int(data.get("rooms"))
    area          = pos_float(data.get("area"))
    floor         = nonneg_int(data.get("floor"))      or 1
    total_floors  = pos_int(data.get("totalFloors"))   or 1
    year_built    = nonneg_int(data.get("yearBuilt"))
    e_oselya      = bool(data.get("eOselya", False))
    images_raw    = data.get("images", [])
    images        = json.dumps([str(u).strip() for u in (images_raw if isinstance(images_raw, list) else [])][:10])
    lat           = data.get("latitude")
    lng           = data.get("longitude")

    VALID_TYPES  = {"квартира","будинок","комерція","земля"}
    VALID_CONDS  = {"нова будова","вторинка","після ремонту","без ремонту"}
    if prop_type not in VALID_TYPES: prop_type = "квартира"
    if condition not in VALID_CONDS: condition = "вторинка"

    errors = {}
    if not title:    errors["title"]    = "Назва обов'язкова"
    if not city:     errors["city"]     = "Місто обов'язкове"
    if not district: errors["district"] = "Район обов'язковий"
    if price is None:  errors["price"]  = "Ціна > 0"
    if rooms is None:  errors["rooms"]  = "Кімнати >= 0"
    if area is None:   errors["area"]   = "Площа > 0"
    if errors:
        return jsonify(error="Невалідні дані", fields=errors), 422

    try:
        lat = float(lat) if lat is not None else None
        lng = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lat = lng = None

    db  = get_db()
    cur = db.execute(
        """INSERT INTO listings
           (user_id,title,city,district,property_type,condition_type,price,rooms,area,
            floor,total_floors,year_built,e_oselya,images,latitude,longitude,description)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (g.user_id, title, city, district, prop_type, condition, price, rooms, area,
         floor, total_floors, year_built, int(e_oselya), images, lat, lng, description),
    )
    db.commit()

    row = db.execute(LISTING_SELECT + " WHERE l.id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(listing=_row_to_listing(row)), 201


@app.route("/api/listings/<int:listing_id>", methods=["DELETE"])
@require_auth
def delete_listing(listing_id: int):
    db  = get_db()
    row = db.execute("SELECT user_id FROM listings WHERE id = ?", (listing_id,)).fetchone()
    if not row:
        return jsonify(error="Оголошення не знайдено"), 404
    if row["user_id"] != g.user_id:
        return jsonify(error="Недостатньо прав"), 403

    db.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    db.commit()
    return jsonify(ok=True)


# ─── Map (geo-based search) ──────────────────────────────────────────────────

@app.route("/api/map/listings", methods=["GET"])
def get_map_listings():
    """Get listings with coordinates for map visualization."""
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

@app.route("/api/analytics/summary", methods=["GET"])
def analytics_summary():
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


# ─── Health check ─────────────────────────────────────────────────────────────

# ─── Health check ─────────────────────────────────────────────────────────────

@app.route("/api/health")
def health():
    return jsonify(status="ok", service="UA Homes API v2")


# ─── Register Blueprints ──────────────────────────────────────────────────

# Import and register admin blueprint
try:
    from admin_routes import admin_bp
    app.register_blueprint(admin_bp)
except ImportError:
    print("Warning: admin_routes not found")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5050))
    print(f"UA Homes API v2 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
