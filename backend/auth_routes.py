"""
UA-Dim Authentication Routes
Modularized blueprint for user registration, login, verification, and password management.
"""

import datetime
import hashlib
import os
import re
import secrets
from functools import wraps

import bcrypt
from flask import Blueprint, current_app, g, jsonify, request, Response

try:
    from app import limiter
except ImportError:
    from backend.app import limiter

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _get_app_module():
    try:
        import app
        return app
    except ImportError:
        from backend import app
        return app


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        app_mod = _get_app_module()
        return app_mod.require_auth(f)(*args, **kwargs)
    return decorated


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("10 per minute")
def register():
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    name = app_mod.strip(data.get("name"), 100)
    email = app_mod.strip(data.get("email"), 254).lower()
    pw = app_mod.strip(data.get("password"), 128)
    account_type = app_mod.normalize_account_type(data.get("accountType") or data.get("account_type"))
    plan_id = app_mod.default_plan_for(account_type)

    if not name:
        return jsonify(error="Вкажіть ім'я"), 422
    if not app_mod.validate_email(email):
        return jsonify(error="Невірний формат email"), 422
    if len(pw) < 8:
        return jsonify(error="Мінімум 8 символів у паролі"), 422

    hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode()
    db = app_mod.get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (name, email, password, account_type, plan_id) VALUES (?, ?, ?, ?, ?)",
            (name, email, hashed, account_type, plan_id),
        )
        db.commit()
    except Exception as exc:
        if not app_mod._is_db_integrity_error(exc):
            raise
        db.rollback()
        return jsonify(error="Цей email вже зареєстровано"), 409

    user_id = cur.lastrowid

    # Generate email verification token and send verification email
    verify_token = secrets.token_urlsafe(32)
    verify_expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=24)).isoformat()
    db.execute(
        "UPDATE users SET email_verify_token=?, email_verify_expires=? WHERE id=?",
        (verify_token, verify_expires, user_id),
    )
    app_mod._refresh_user_growth_summary(db)
    db.commit()
    app_mod.cache_delete_prefix("admin:reports:user-growth:")
    verify_email_sent = app_mod.send_email_verify(email, verify_token)

    return jsonify(
        token=app_mod.make_token(user_id, email),
        user={
            "id": user_id,
            "name": name,
            "email": email,
            "email_verified": 0,
            "account_type": account_type,
            "plan_id": plan_id,
            "plan": app_mod.plan_public_dict(plan_id),
        },
        verify_email_sent=verify_email_sent,
    ), 201


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("20 per minute")
def login():
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    email = app_mod.strip(data.get("email"), 254).lower()
    pw = app_mod.strip(data.get("password"), 128)

    db = app_mod.get_db()
    row = db.execute(
        "SELECT * FROM users WHERE email = ? AND status = 'active'",
        (email,),
    ).fetchone()

    stored_password = row["password_hash"] if row and app_mod._has_key(row, "password_hash") else None
    if not stored_password and row:
        stored_password = row["password"]

    if not row or not app_mod._password_matches(pw, stored_password):
        return jsonify(error="Невірний email або пароль"), 401

    plan_id, _plan = app_mod.resolve_user_plan(row)
    return jsonify(
        token=app_mod.make_token(
            row["id"],
            row["email"],
            row["auth_token_version"] if app_mod._has_key(row, "auth_token_version") else 0,
        ),
        user={
            "id": row["id"],
            "name": row["name"],
            "email": row["email"],
            "account_type": app_mod.normalize_account_type(row["account_type"] if app_mod._has_key(row, "account_type") else None),
            "plan_id": plan_id,
            "plan": app_mod.plan_public_dict(plan_id),
        },
    )


@auth_bp.route("/me", methods=["GET", "PATCH"])
@require_auth
def me():
    app_mod = _get_app_module()
    db = app_mod.get_db()
    if request.method == "PATCH":
        data = request.get_json(silent=True) or {}
        if "name" in data:
            name = app_mod.strip(data.get("name"), 100)
            if not name:
                return jsonify(error="Вкажіть ім'я"), 422
            db.execute("UPDATE users SET name = ? WHERE id = ?", (name, g.user_id))

        raw_account_type = data.get("accountType", data.get("account_type"))
        if raw_account_type is not None:
            account_type = app_mod.normalize_account_type(raw_account_type)
            current = db.execute("SELECT plan_id FROM users WHERE id = ?", (g.user_id,)).fetchone()
            current_plan = str((current["plan_id"] if current else "") or "").strip()
            # A plan belongs to a single audience, so switching cabinets resets it.
            if app_mod.SUBSCRIPTION_PLANS.get(current_plan, {}).get("audience") != account_type:
                db.execute(
                    "UPDATE users SET account_type = ?, plan_id = ?, plan_expires_at = NULL WHERE id = ?",
                    (account_type, app_mod.default_plan_for(account_type), g.user_id),
                )
            else:
                db.execute("UPDATE users SET account_type = ? WHERE id = ?", (account_type, g.user_id))
        db.commit()

    row = db.execute(
        "SELECT id, name, email, email_verified, phone_verified, phone,"
        " account_type, plan_id, plan_expires_at, agency_slug"
        " FROM users WHERE id = ?",
        (g.user_id,),
    ).fetchone()
    if not row:
        return jsonify(error="Користувача не знайдено"), 404

    user = dict(row)
    plan_id, plan = app_mod.resolve_user_plan(row)
    user["account_type"] = app_mod.normalize_account_type(user.get("account_type"))
    user["plan_id"] = plan_id
    user["plan"] = app_mod.plan_public_dict(plan_id)
    user["usage"] = app_mod.listing_usage(db, g.user_id, plan)
    return jsonify(user=user)


@auth_bp.route("/verify-email", methods=["GET"])
def verify_email():
    app_mod = _get_app_module()
    token = app_mod.strip(request.args.get("token", ""), 200)
    if not token:
        return jsonify(error="Token required"), 400
    db = app_mod.get_db()
    row = db.execute(
        "SELECT id, email_verify_expires FROM users WHERE email_verify_token = ?", (token,)
    ).fetchone()
    if not row:
        return jsonify(error="Невірний або прострочений токен"), 400
    expires = row["email_verify_expires"] or ""
    try:
        if datetime.datetime.fromisoformat(expires) < datetime.datetime.utcnow():
            return jsonify(error="Токен прострочено. Запросіть новий."), 400
    except Exception:
        return jsonify(error="Невірний токен"), 400
    db.execute(
        "UPDATE users SET email_verified=1, email_verify_token=NULL, email_verify_expires=NULL WHERE id=?",
        (row["id"],),
    )
    db.commit()
    return Response(
        f'<meta http-equiv="refresh" content="0;url={app_mod.public_app_url()}?email_verified=1">',
        mimetype="text/html",
    )


@auth_bp.route("/resend-verification", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification():
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    email = app_mod.strip(data.get("email", ""), 254).lower()
    if not email:
        return jsonify(error="Email required"), 400
    db = app_mod.get_db()
    row = db.execute(
        "SELECT id, email_verified FROM users WHERE email = ?", (email,)
    ).fetchone()
    if not row:
        return jsonify(ok=True)
    if row["email_verified"]:
        return jsonify(ok=True, already_verified=True)
    token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(hours=24)).isoformat()
    db.execute(
        "UPDATE users SET email_verify_token=?, email_verify_expires=? WHERE id=?",
        (token, expires, row["id"]),
    )
    db.commit()
    if not app_mod.send_email_verify(email, token):
        return jsonify(error="Email delivery is not configured"), 503
    return jsonify(ok=True)


@auth_bp.route("/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    """Request a password reset link. Non-enumerating: returns 200 for any email."""
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    email = app_mod.strip(data.get("email", ""), 254).lower()
    if not app_mod.validate_email(email):
        return jsonify(error="Invalid email"), 400

    # Fail clearly before claiming delivery when no provider is configured in production.
    if app_mod._production_secret_required() and not app_mod._email_provider_configured():
        return jsonify(error="Email delivery is not configured"), 503

    db = app_mod.get_db()
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        # Non-enumerating response: do not reveal whether the address exists.
        return jsonify(ok=True)

    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=30)).isoformat()
    db.execute(
        "UPDATE users SET password_reset_token_hash=?, password_reset_expires=? WHERE id=?",
        (token_hash, expires, row["id"]),
    )
    db.commit()

    reset_url = f"{app_mod.public_seller_url()}#reset_token={raw_token}"
    subject = "Відновлення пароля — UA-Dim"
    body_text = f"Для відновлення пароля перейдіть за посиланням (дійсне 30 хв): {reset_url}"
    body_html = (
        f"<p>Ви отримали запит на відновлення пароля для вашого облікового запису UA-Dim.</p>"
        f'<p><a href="{reset_url}">Встановити новий пароль</a></p>'
        f"<p>Посилання дійсне 30 хвилин. Якщо ви не робили цей запит — проігноруйте листа.</p>"
    )

    if app_mod._email_provider_configured():
        ok = app_mod._send_email(email, subject, body_text, body_html)
        if not ok:
            current_app.logger.error("Password reset email delivery failed for user_id=%s", row["id"])
            db.execute(
                "UPDATE users SET password_reset_token_hash=NULL, password_reset_expires=NULL WHERE id=?",
                (row["id"],),
            )
            db.commit()
            # Keep the response non-enumerating even when delivery fails for a real account.
            return jsonify(ok=True)
    else:
        # Dev-only fallback: log reset URL; never reached in production.
        current_app.logger.info("PASSWORD RESET (dev) → %s | URL: %s", email, reset_url)

    return jsonify(ok=True)


@auth_bp.route("/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password():
    """Consume a password-reset token and set a new password."""
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    raw_token = app_mod.strip(data.get("token", ""), 200)
    new_pw = app_mod.strip(data.get("password", ""), 128)

    if not raw_token:
        return jsonify(error="Token required"), 400
    if len(new_pw) < 8:
        return jsonify(error="Password must be at least 8 characters"), 422

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    db = app_mod.get_db()
    row = db.execute(
        "SELECT id, password_reset_expires FROM users WHERE password_reset_token_hash = ?",
        (token_hash,),
    ).fetchone()

    if not row:
        return jsonify(error="Invalid or expired reset token"), 400

    expires = row["password_reset_expires"] or ""
    try:
        if datetime.datetime.fromisoformat(expires) < datetime.datetime.utcnow():
            return jsonify(error="Reset token has expired"), 400
    except Exception:
        return jsonify(error="Invalid reset token"), 400

    hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(rounds=12)).decode()
    # Set both legacy password and password_hash columns; clear token to prevent replay.
    cursor = db.execute(
        "UPDATE users SET password=?, password_hash=?,"
        " password_reset_token_hash=NULL, password_reset_expires=NULL,"
        " auth_token_version=auth_token_version + 1"
        " WHERE id=? AND password_reset_token_hash=?",
        (hashed, hashed, row["id"], token_hash),
    )
    if cursor.rowcount != 1:
        db.rollback()
        return jsonify(error="Invalid or expired reset token"), 400
    db.commit()
    return jsonify(ok=True)


@auth_bp.route("/send-phone-code", methods=["POST"])
@require_auth
@limiter.limit("5 per hour")
def send_phone_code():
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    phone = app_mod.strip(data.get("phone", ""), 20)
    if not phone or not re.match(r"^\+?\d{7,15}$", phone):
        return jsonify(error="Невірний формат номера телефону"), 422

    is_prod = app_mod._production_secret_required()
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_phone = os.environ.get("TWILIO_FROM_PHONE", "")
    twilio_configured = bool(account_sid and auth_token and from_phone)

    # In production, refuse immediately if no SMS provider is available.
    if is_prod and not twilio_configured:
        return jsonify(error="SMS delivery is not configured"), 503

    code = str(secrets.randbelow(900000) + 100000)  # 6-digit code
    result = app_mod.send_sms_verify(phone, code)

    if result is False:
        # Twilio was configured but the send failed — do not persist the code.
        return jsonify(error="SMS delivery failed"), 502

    if result is None and is_prod:
        # Should not reach here after the guard above, but be defensive.
        return jsonify(error="SMS delivery is not configured"), 503

    # Only persist the code after a confirmed send (True) or in dev with no provider (None, non-prod).
    expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat()
    db = app_mod.get_db()
    db.execute(
        "UPDATE users SET phone=?, phone_verify_code=?, phone_verify_expires=? WHERE id=?",
        (phone, code, expires, g.user_id),
    )
    db.commit()

    # Expose dev_code only when there is no provider and we are not in production.
    dev_code = code if (result is None and not is_prod) else None
    return jsonify(ok=True, dev_code=dev_code)


@auth_bp.route("/verify-phone", methods=["POST"])
@require_auth
@limiter.limit("10 per hour")
def verify_phone():
    app_mod = _get_app_module()
    data = request.get_json(silent=True) or {}
    code = app_mod.strip(data.get("code", ""), 10)
    if not code:
        return jsonify(error="Code required"), 400
    db = app_mod.get_db()
    row = db.execute(
        "SELECT phone_verify_code, phone_verify_expires FROM users WHERE id=?", (g.user_id,)
    ).fetchone()
    if not row or row["phone_verify_code"] != code:
        return jsonify(error="Невірний код"), 400
    try:
        if datetime.datetime.fromisoformat(row["phone_verify_expires"] or "") < datetime.datetime.utcnow():
            return jsonify(error="Код прострочено. Запросіть новий."), 400
    except Exception:
        return jsonify(error="Код прострочено"), 400
    db.execute(
        "UPDATE users SET phone_verified=1, phone_verify_code=NULL, phone_verify_expires=NULL WHERE id=?",
        (g.user_id,),
    )
    db.commit()
    return jsonify(ok=True, phone_verified=True)
