"""
UA-Dim Payment Routes
Modularized blueprint for LiqPay integration, order processing, and subscription plan management.
"""

import base64
import datetime
import hashlib
import ipaddress
import json
import os
import re
import secrets
import time
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import quote, urlsplit

from flask import Blueprint, current_app, g, jsonify, request

try:
    from app import limiter
except ImportError:
    from backend.app import limiter

payment_bp = Blueprint("payment", __name__, url_prefix="/api/payment")


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


def _liqpay_sign(private_key: str, data: str) -> str:
    """Generate LiqPay signature: base64(sha1(private_key + data + private_key))"""
    raw = private_key + data + private_key
    sha = hashlib.sha1(raw.encode("utf-8")).digest()
    return base64.b64encode(sha).decode("utf-8")


def _liqpay_encode(payload: dict, private_key: str) -> tuple[str, str]:
    """Encode LiqPay payload; return (data_b64, signature)."""
    data_b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("utf-8")
    signature = _liqpay_sign(private_key, data_b64)
    return data_b64, signature


LIQPAY_MODES = {"disabled", "sandbox", "live"}
LIQPAY_FAILURE_STATUSES = {
    "error",
    "failure",
    "reversed",
    "unsubscribed",
}


def _is_external_https_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        return False
    if host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".test", ".example", ".invalid")
    ):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def _liqpay_config() -> tuple[str, str, str, str | None]:
    """Return validated mode and keys without exposing credential details."""
    mode = os.environ.get("LIQPAY_MODE", "disabled").strip().lower() or "disabled"
    public_key = os.environ.get("LIQPAY_PUBLIC_KEY", "").strip()
    private_key = os.environ.get("LIQPAY_PRIVATE_KEY", "").strip()

    if mode not in LIQPAY_MODES:
        return mode, public_key, private_key, "invalid_mode"
    if mode == "disabled":
        return mode, public_key, private_key, None
    if not public_key or not private_key:
        return mode, public_key, private_key, "missing_keys"

    public_is_sandbox = public_key.startswith("sandbox_")
    private_is_sandbox = private_key.startswith("sandbox_")
    if mode == "sandbox" and not (public_is_sandbox and private_is_sandbox):
        return mode, public_key, private_key, "sandbox_key_mismatch"
    if mode == "live" and (public_is_sandbox or private_is_sandbox):
        return mode, public_key, private_key, "live_key_mismatch"
    if mode == "live":
        public_url = os.environ.get("UA_HOMES_PUBLIC_URL", "").strip().rstrip("/")
        api_url = os.environ.get("UA_HOMES_API", "").strip().rstrip("/") or public_url
        for name, value in (("public_url", public_url), ("api_url", api_url)):
            if not _is_external_https_base_url(value):
                return mode, public_key, private_key, f"invalid_{name}"
    return mode, public_key, private_key, None


def _liqpay_amount_matches(expected, actual) -> bool:
    try:
        return Decimal(str(expected)) == Decimal(str(actual))
    except (InvalidOperation, TypeError, ValueError):
        return False


def _payment_unavailable(config_error: str | None = None):
    if config_error:
        current_app.logger.error("LiqPay configuration rejected: %s", config_error)
    return jsonify(
        error="Платежі тимчасово недоступні",
        code="payments_disabled" if not config_error else "payments_misconfigured",
    ), 503


LEGACY_PLAN_ALIASES = {"agent": "realtor_pro"}


def resolve_plan_id(raw) -> str | None:
    """Map an incoming plan id (including legacy ids) to a known paid plan."""
    app_mod = _get_app_module()
    candidate = str(raw or "").strip()
    candidate = LEGACY_PLAN_ALIASES.get(candidate, candidate)
    return candidate if candidate in app_mod.PAID_PLAN_IDS else None


def _reversal_previous_entitlement(db, order) -> tuple[str, str | None]:
    """Restore only entitlements still backed by a non-reversed paid order."""
    app_mod = _get_app_module()
    order_plan_id = str(order["plan_id"] or "")
    previous_plan_id = str(order["previous_plan_id"] or "")
    previous_expiry = order["previous_plan_expires_at"]
    if previous_plan_id not in app_mod.SUBSCRIPTION_PLANS:
        return app_mod.default_plan_for(app_mod.SUBSCRIPTION_PLANS[order_plan_id]["audience"]), None
    if previous_plan_id in app_mod.PAID_PLAN_IDS:
        supporting_order = db.execute(
            "SELECT order_id FROM premium_orders"
            " WHERE user_id = ? AND plan_id = ? AND status = 'paid' AND order_id <> ?"
            " LIMIT 1",
            (order["user_id"], previous_plan_id, order["order_id"]),
        ).fetchone()
        if not supporting_order:
            return app_mod.default_plan_for(app_mod.SUBSCRIPTION_PLANS[previous_plan_id]["audience"]), None
    return previous_plan_id, previous_expiry


@payment_bp.route("/liqpay/create", methods=["POST"])
@require_auth
@limiter.limit("20 per hour")
def payment_liqpay_create():
    """Create LiqPay payment: return data + signature for checkout form."""
    app_mod = _get_app_module()
    body = request.get_json(silent=True) or {}
    plan_id = resolve_plan_id(body.get("plan_id"))

    if not plan_id:
        return jsonify(error="Unknown plan"), 400

    plan = app_mod.SUBSCRIPTION_PLANS[plan_id]
    mode, public_key, private_key, config_error = _liqpay_config()
    if mode == "disabled":
        return _payment_unavailable()
    if config_error:
        return _payment_unavailable(config_error)

    db = app_mod.get_db()
    public_url = os.environ.get("UA_HOMES_PUBLIC_URL", "").strip().rstrip("/") or "http://localhost:5050"
    api_url = os.environ.get("UA_HOMES_API", "").strip().rstrip("/") or public_url
    order_id = f"uadim-{plan_id}-{int(time.time())}-{secrets.token_hex(4)}"

    # Persist the order up front so the callback can attribute it to a user.
    try:
        db.execute(
            "INSERT INTO premium_orders"
            " (order_id, plan_id, amount, currency, status, user_id, environment)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (order_id, plan_id, plan["price"], "UAH", g.user_id, mode),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        current_app.logger.error("LiqPay order persistence failed: %s", exc)
        return jsonify(error="Не вдалося створити замовлення", code="order_create_failed"), 503

    payload = {
        "public_key": public_key,
        "version": "3",
        "action": "pay",
        "amount": plan["price"],
        "currency": "UAH",
        "description": f"UA-Dim {plan['name']} — {plan['price']} UAH/міс",
        "order_id": order_id,
        "result_url": f"{public_url}/?payment=return&order_id={quote(order_id)}",
        "server_url": f"{api_url}/api/payment/liqpay/callback",
        "language": "uk",
    }
    if mode == "sandbox":
        payload["sandbox"] = 1

    data_b64, signature = _liqpay_encode(payload, private_key)
    return jsonify(data=data_b64, signature=signature, order_id=order_id, mode=mode)


@payment_bp.route("/liqpay/callback", methods=["POST"])
def payment_liqpay_callback():
    """Verify a LiqPay callback and activate a paid plan exactly once."""
    app_mod = _get_app_module()
    mode, public_key, private_key, config_error = _liqpay_config()
    if mode == "disabled":
        return "payments_disabled", 503
    if config_error:
        current_app.logger.error("LiqPay callback configuration rejected: %s", config_error)
        return "payments_misconfigured", 503

    data_b64 = request.form.get("data", "")
    signature = request.form.get("signature", "")

    if not data_b64 or not signature or len(data_b64) > 100_000 or len(signature) > 500:
        return "invalid_request", 400

    expected_sig = _liqpay_sign(private_key, data_b64)
    if not secrets.compare_digest(expected_sig, signature):
        current_app.logger.error("LiqPay callback: invalid signature")
        return "signature_mismatch", 400

    try:
        payload = json.loads(base64.b64decode(data_b64, validate=True).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return "decode_error", 400
    if not isinstance(payload, dict):
        return "invalid_payload", 400

    status = str(payload.get("status") or "").strip().lower()
    order_id = str(payload.get("order_id") or "").strip()
    amount = payload.get("amount")
    currency = str(payload.get("currency") or "").strip().upper()
    action = str(payload.get("action") or "").strip().lower()
    callback_public_key = str(payload.get("public_key") or "").strip()
    provider_payment_id = str(payload.get("payment_id") or "").strip()

    if not re.fullmatch(r"uadim-[a-z0-9_]+-\d{9,12}-[a-f0-9]{8}", order_id):
        return "invalid_order_id", 400
    if action != "pay" or callback_public_key != public_key:
        return "provider_mismatch", 400

    db = app_mod.get_db()
    existing = db.execute(
        "SELECT order_id, user_id, plan_id, amount, currency, status, environment,"
        " provider_payment_id, previous_plan_id, previous_plan_expires_at,"
        " activated_plan_expires_at, entitlement_chain_id"
        " FROM premium_orders WHERE order_id = ?",
        (order_id,),
    ).fetchone()
    if not existing:
        return "unknown_order", 404

    if existing["environment"] != mode:
        return "environment_mismatch", 409
    if currency != str(existing["currency"] or "").upper():
        return "currency_mismatch", 400
    if not _liqpay_amount_matches(existing["amount"], amount):
        return "amount_mismatch", 400

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
    expected_paid_status = "sandbox" if mode == "sandbox" else "success"
    if status == "reversed":
        previous_payment_id = str(existing["provider_payment_id"] or "")
        if previous_payment_id and previous_payment_id != provider_payment_id:
            return "payment_id_mismatch", 409
        try:
            reversal = db.execute(
                "UPDATE premium_orders SET status = 'reversing', provider_status = ?,"
                " provider_payment_id = ?, processed_at = ?"
                " WHERE order_id = ? AND status = 'paid'",
                (status, provider_payment_id or previous_payment_id or None, now, order_id),
            )
            if reversal.rowcount == 1:
                db.execute(
                    "UPDATE users SET plan_id = plan_id WHERE id = ?",
                    (existing["user_id"],),
                )
                user = db.execute(
                    "SELECT plan_id, plan_expires_at FROM users WHERE id = ?",
                    (existing["user_id"],),
                ).fetchone()
                activation_expiry = str(existing["activated_plan_expires_at"] or "")
                order_plan_id = str(existing["plan_id"] or "")
                user_plan_id = str(user["plan_id"] or "") if user else ""
                user_expiry = str(user["plan_expires_at"] or "") if user else ""
                active_order = None
                if user and user_plan_id == order_plan_id:
                    active_order = db.execute(
                        "SELECT order_id, entitlement_chain_id FROM premium_orders"
                        " WHERE user_id = ? AND plan_id = ?"
                        " AND status IN ('paid', 'reversing')"
                        " AND activated_plan_expires_at = ?"
                        " ORDER BY paid_at DESC, id DESC LIMIT 1",
                        (existing["user_id"], order_plan_id, user_expiry),
                    ).fetchone()
                    if not active_order:
                        active_order = db.execute(
                            "SELECT order_id, entitlement_chain_id FROM premium_orders"
                            " WHERE user_id = ? AND plan_id = ?"
                            " AND status IN ('paid', 'reversing')"
                            " ORDER BY paid_at DESC, id DESC LIMIT 1",
                            (existing["user_id"], order_plan_id),
                        ).fetchone()
                active_chain_id = (
                    str(active_order["entitlement_chain_id"] or active_order["order_id"])
                    if active_order
                    else ""
                )
                order_chain_id = str(existing["entitlement_chain_id"] or existing["order_id"])
                contributes_to_active_entitlement = active_chain_id == order_chain_id

                if (
                    user
                    and user_plan_id == order_plan_id
                    and contributes_to_active_entitlement
                    and activation_expiry
                    and user_expiry == activation_expiry
                ):
                    previous_plan_id, previous_expiry = _reversal_previous_entitlement(db, existing)
                    db.execute(
                        "UPDATE users SET plan_id = ?, plan_expires_at = ?, account_type = ?"
                        " WHERE id = ?",
                        (
                            previous_plan_id,
                            previous_expiry,
                            app_mod.SUBSCRIPTION_PLANS[previous_plan_id]["audience"],
                            existing["user_id"],
                        ),
                    )
                elif user and user_plan_id == order_plan_id and contributes_to_active_entitlement:
                    if not user_expiry:
                        raise ValueError("active paid plan has no expiry")
                    parsed_expiry = datetime.datetime.fromisoformat(user_expiry.replace(" ", "T"))
                    reduced_expiry = parsed_expiry - datetime.timedelta(
                        days=app_mod.SUBSCRIPTION_PLANS[order_plan_id]["duration_days"]
                    )
                    if reduced_expiry > datetime.datetime.utcnow():
                        db.execute(
                            "UPDATE users SET plan_expires_at = ? WHERE id = ?",
                            (
                                reduced_expiry.replace(microsecond=0).isoformat(sep=" "),
                                existing["user_id"],
                            ),
                        )
                    else:
                        previous_plan_id, previous_expiry = _reversal_previous_entitlement(db, existing)
                        db.execute(
                            "UPDATE users SET plan_id = ?, plan_expires_at = ?, account_type = ?"
                            " WHERE id = ?",
                            (
                                previous_plan_id,
                                previous_expiry,
                                app_mod.SUBSCRIPTION_PLANS[previous_plan_id]["audience"],
                                existing["user_id"],
                            ),
                        )
                db.execute(
                    "UPDATE premium_orders SET status = 'reversed', processed_at = ?"
                    " WHERE order_id = ? AND status = 'reversing'",
                    (now, order_id),
                )
                db.commit()
                return "ok", 200

            pending_reversal = db.execute(
                "UPDATE premium_orders SET status = 'reversed', provider_status = ?,"
                " provider_payment_id = ?, processed_at = ?"
                " WHERE order_id = ? AND status NOT IN ('paid', 'processing', 'reversing', 'reversed')",
                (status, provider_payment_id or None, now, order_id),
            )
            if pending_reversal.rowcount == 1:
                db.commit()
            else:
                db.rollback()
            return "ok", 200
        except Exception as exc:
            db.rollback()
            current_app.logger.error("LiqPay reversal processing failed for order %s: %s", order_id, exc)
            return "processing_error", 500

    if status != expected_paid_status:
        normalized_status = "failed" if status in LIQPAY_FAILURE_STATUSES else "pending"
        if status in {"sandbox", "success"}:
            normalized_status = "rejected"
        if existing["status"] != "paid":
            transition = db.execute(
                "UPDATE premium_orders SET status = ?, provider_status = ?,"
                " provider_payment_id = ?, processed_at = ?"
                " WHERE order_id = ?"
                " AND status NOT IN ('paid', 'processing', 'reversing', 'reversed')",
                (normalized_status, status or None, provider_payment_id or None, now, order_id),
            )
            if transition.rowcount == 1:
                db.commit()
            else:
                db.rollback()
        return "ok", 200

    if not provider_payment_id:
        return "missing_payment_id", 400
    if existing["status"] == "paid":
        previous_payment_id = str(existing["provider_payment_id"] or "")
        if previous_payment_id and previous_payment_id != provider_payment_id:
            return "payment_id_mismatch", 409
        return "ok", 200

    plan_id = resolve_plan_id(existing["plan_id"])
    user_id = existing["user_id"]
    if not plan_id or not user_id:
        return "order_not_attributable", 409

    try:
        user_lock = db.execute(
            "UPDATE users SET plan_id = plan_id WHERE id = ?",
            (user_id,),
        )
        if user_lock.rowcount != 1:
            db.rollback()
            return "unknown_user", 409
        user = db.execute(
            "SELECT id, plan_id, plan_expires_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        entitlement_chain_id = order_id
        if (
            str(user["plan_id"] or "") == plan_id
            and str(user["plan_expires_at"] or "")
        ):
            active_order = db.execute(
                "SELECT order_id, entitlement_chain_id FROM premium_orders"
                " WHERE user_id = ? AND plan_id = ? AND status = 'paid'"
                " AND activated_plan_expires_at = ?"
                " ORDER BY paid_at DESC, id DESC LIMIT 1",
                (user_id, plan_id, user["plan_expires_at"]),
            ).fetchone()
            if active_order:
                entitlement_chain_id = str(
                    active_order["entitlement_chain_id"] or active_order["order_id"]
                )
        claim = db.execute(
            "UPDATE premium_orders SET status = 'processing', provider_status = ?,"
            " provider_payment_id = ?, processed_at = ?, previous_plan_id = ?,"
            " previous_plan_expires_at = ?, entitlement_chain_id = ?"
            " WHERE order_id = ?"
            " AND status NOT IN ('paid', 'processing', 'reversing', 'reversed')",
            (
                status,
                provider_payment_id,
                now,
                user["plan_id"],
                user["plan_expires_at"],
                entitlement_chain_id,
                order_id,
            ),
        )
        if claim.rowcount != 1:
            db.rollback()
            latest = db.execute(
                "SELECT status, provider_payment_id FROM premium_orders WHERE order_id = ?",
                (order_id,),
            ).fetchone()
            if latest and latest["status"] == "paid":
                if str(latest["provider_payment_id"] or "") != provider_payment_id:
                    return "payment_id_mismatch", 409
                return "ok", 200
            return "ok", 200

        app_mod.apply_plan_to_user(db, int(user_id), plan_id)
        activated_user = db.execute(
            "SELECT plan_expires_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        db.execute(
            "UPDATE premium_orders SET status = 'paid', paid_at = ?, processed_at = ?,"
            " activated_plan_expires_at = ?"
            " WHERE order_id = ? AND status = 'processing'",
            (
                now,
                now,
                activated_user["plan_expires_at"] if activated_user else None,
                order_id,
            ),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        current_app.logger.error("LiqPay callback processing failed for order %s: %s", order_id, exc)
        return "processing_error", 500

    return "ok", 200


@payment_bp.route("/orders/<order_id>", methods=["GET"])
@require_auth
@limiter.limit("120 per hour")
def payment_order_status(order_id: str):
    """Return the authenticated user's server-confirmed payment state."""
    app_mod = _get_app_module()
    if not re.fullmatch(r"uadim-[a-z0-9_]+-\d{9,12}-[a-f0-9]{8}", order_id):
        return jsonify(error="Unknown order"), 404
    db = app_mod.get_db()
    row = db.execute(
        "SELECT order_id, plan_id, amount, currency, status, provider_status, environment"
        " FROM premium_orders WHERE order_id = ? AND user_id = ?",
        (order_id, g.user_id),
    ).fetchone()
    if not row:
        return jsonify(error="Unknown order"), 404
    plan_id = resolve_plan_id(row["plan_id"])
    return jsonify(
        order_id=row["order_id"],
        plan_id=plan_id,
        amount=row["amount"],
        currency=row["currency"],
        status=row["status"],
        provider_status=row["provider_status"],
        environment=row["environment"],
        paid=row["status"] == "paid",
    )


@payment_bp.route("/plans", methods=["GET"])
def payment_plans():
    """Public endpoint: return available plans grouped by audience."""
    app_mod = _get_app_module()
    audience = str(request.args.get("audience", "")).strip().lower()
    plans = [app_mod.plan_public_dict(plan_id) for plan_id in app_mod.SUBSCRIPTION_PLANS]
    if audience in app_mod.ACCOUNT_TYPES:
        plans = [plan for plan in plans if plan["audience"] == audience]
    return jsonify(
        plans=plans,
        owner=[plan for plan in plans if plan["audience"] == "owner"],
        realtor=[plan for plan in plans if plan["audience"] == "realtor"],
    )
