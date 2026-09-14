"""
UA-Dim Agencies and Market Insights / Content Routes
Modularized blueprint for agency directory and content/insights engine.
"""

import html
import sqlite3
import sys
from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, request

content_bp = Blueprint("content_bp", __name__)


def _get_app_module():
    """Dynamically get the main app module to access shared globals and helpers."""
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


def _response_score(avg_response_minutes: int | None) -> int:
    if avg_response_minutes is None:
        return 45
    if avg_response_minutes <= 15:
        return 100
    if avg_response_minutes <= 30:
        return 88
    if avg_response_minutes <= 60:
        return 72
    if avg_response_minutes <= 120:
        return 58
    return 42


def _freshness_score(freshness_index: float | None) -> int:
    if freshness_index is None:
        return 50
    return max(20, min(100, int(round(freshness_index))))


def _agency_metrics(
    db: sqlite3.Connection,
    where_sql: str = "",
    where_params: tuple = (),
    sort_by: str = "reputation",
    limit: int = 30,
    include_management: bool = False,
):
    query = f"""
        SELECT
            ap.slug,
            ap.name,
            ap.kind,
            ap.city,
            ap.specialization,
            ap.is_verified,
            ap.status,
            ap.avg_response_minutes,
            ap.team_size,
            ap.completed_deals,
            ap.last_verified_at,
            ap.revision,
            ap.created_at,
            ap.updated_at,
            COUNT(CASE WHEN l.status = 'published' THEN 1 END) AS active_listings,
            COUNT(l.id) AS total_listings,
            ROUND(AVG(
                CASE WHEN l.status = 'published'
                    THEN (CASE WHEN l.verified_owner = 1 THEN 1 ELSE 0 END
                        + CASE WHEN l.verified_phone = 1 THEN 1 ELSE 0 END
                        + CASE WHEN l.verified_docs = 1 THEN 1 ELSE 0 END) / 3.0
                END
            ) * 100, 1) AS verified_rate
            ,
            ROUND(AVG(
                CASE WHEN l.status = 'published'
                    THEN CASE WHEN l.moderation_status = 'approved' THEN 1 ELSE 0 END
                END
            ) * 100, 1) AS moderation_rate,
            ROUND(AVG(
                CASE WHEN l.status = 'published'
                    THEN CASE
                        WHEN l.listing_status = 'active' THEN 100
                        WHEN l.listing_status = 'sold' THEN 75
                        WHEN l.listing_status = 'removed' THEN 40
                        ELSE 60
                    END
                END
            ), 1) AS freshness_index
        FROM agency_profiles ap
        LEFT JOIN listings l ON l.agency_slug = ap.slug
        {where_sql}
        GROUP BY ap.slug, ap.name, ap.kind, ap.city, ap.specialization, ap.is_verified,
                 ap.status, ap.avg_response_minutes, ap.team_size, ap.completed_deals,
                 ap.last_verified_at, ap.revision, ap.created_at, ap.updated_at
        ORDER BY ap.is_verified DESC, active_listings DESC, ap.name ASC
        LIMIT ?
    """
    rows = db.execute(query, tuple(where_params) + (limit,)).fetchall()
    metrics: list[dict] = []
    for row in rows:
        avg_response_minutes = row["avg_response_minutes"]
        active_listings = int(row["active_listings"] or 0)
        verified_rate = float(row["verified_rate"] or 0)
        moderation_rate = float(row["moderation_rate"] or 0)
        freshness_index = float(row["freshness_index"]) if row["freshness_index"] is not None else None
        response_score = _response_score(avg_response_minutes)
        freshness_score = _freshness_score(freshness_index)
        reputation_score = int(round(
            verified_rate * 0.4
            + response_score * 0.22
            + freshness_score * 0.2
            + moderation_rate * 0.18
            + (5 if row["is_verified"] else 0)
        ))
        team_size = row["team_size"] if row["team_size"] is not None else max(2, min(60, active_listings // 3 + 2))
        if reputation_score >= 85:
            reputation_tier = "A+"
        elif reputation_score >= 75:
            reputation_tier = "A"
        elif reputation_score >= 65:
            reputation_tier = "B"
        else:
            reputation_tier = "C"

        item = {
            "slug": row["slug"],
            "name": row["name"],
            "kind": row["kind"],
            "city": row["city"],
            "specialization": row["specialization"] or "",
            "is_verified": bool(row["is_verified"]),
            "avg_response_minutes": avg_response_minutes,
            "team_size": int(team_size),
            "completed_deals": int(row["completed_deals"] or 0),
            "last_verified_at": row["last_verified_at"],
            "active_listings": active_listings,
            "total_listings": int(row["total_listings"] or 0),
            "verified_rate": verified_rate,
            "moderation_rate": moderation_rate,
            "freshness_index": freshness_index,
            "response_score": response_score,
            "freshness_score": freshness_score,
            "reputation_score": reputation_score,
            "reputation_tier": reputation_tier,
        }
        if include_management:
            item.update({
                "status": row["status"],
                "revision": int(row["revision"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        metrics.append(item)

    if sort_by == "active":
        metrics.sort(key=lambda item: (item["active_listings"], item["reputation_score"]), reverse=True)
    elif sort_by == "response":
        metrics.sort(key=lambda item: (item["response_score"], item["reputation_score"]), reverse=True)
    elif sort_by == "verified_rate":
        metrics.sort(key=lambda item: (item["verified_rate"], item["reputation_score"]), reverse=True)
    else:
        metrics.sort(key=lambda item: (item["reputation_score"], item["active_listings"]), reverse=True)
    return metrics


def _seo_landing_stats(db: sqlite3.Connection, limit: int = 8):
    city_rows = db.execute(
        """
        SELECT city, COUNT(*) as cnt, ROUND(AVG(price)) as avg_price
        FROM listings
        WHERE status = 'published'
        GROUP BY city
        ORDER BY cnt DESC, city ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    district_rows = db.execute(
        """
        SELECT city, district, COUNT(*) as cnt, ROUND(AVG(price)) as avg_price
        FROM listings
        WHERE status = 'published'
        GROUP BY city, district
        ORDER BY cnt DESC, city ASC, district ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return city_rows, district_rows


def _content_articles(db: sqlite3.Connection) -> list[dict]:
    app_module = _get_app_module()
    city_rows, district_rows = _seo_landing_stats(db, limit=6)
    agency_rows = _agency_metrics(
        db, where_sql="WHERE ap.status = 'active'", sort_by="reputation", limit=4
    )

    top_city = city_rows[0] if city_rows else None
    top_district = district_rows[0] if district_rows else None
    top_agency = agency_rows[0] if agency_rows else None
    freshness_row = db.execute(
        "SELECT COUNT(*) FROM listings WHERE status = 'published' AND created_at >= date('now', '-14 day')"
    ).fetchone()
    freshness_count = int(freshness_row[0] or 0) if freshness_row else 0
    e_oselya_count = int(
        db.execute(
            "SELECT COUNT(*) FROM listings WHERE status = 'published' AND e_oselya = 1"
        ).fetchone()[0]
        or 0
    )

    public_app_url = getattr(app_module, "public_app_url", lambda: "/")

    articles = [
        {
            "slug": "e-oselya-catalog-insights",
            "category": "єОселя",
            "title": "єОселя 2026: як швидко знаходити акредитоване житло",
            "excerpt": (
                f"У каталозі UA-Dim зараз доступно {e_oselya_count} перевірених об'єктів під програму єОселя (3% та 7%)."
                if e_oselya_count
                else "Гід вибору житла під держпрограму єОселя з фокусом на первинку та безпечні угоди."
            ),
            "published_at": "2026-08-15",
            "reading_time": 4,
            "featured": True,
            "stats": [
                {"label": "Об'єктів єОселя", "value": e_oselya_count},
                {"label": "Ставка", "value": "3% / 7%"},
            ],
            "body_html": (
                "<p>Програма єОселя вимагає суворого скорингу документів і прав власності. "
                "Ми маркуємо перевірені пропозиції окремим бейджем та фільтром, щоб покупець не витрачав тижні на неакредитовані квартири.</p>"
                "<p>Рекомендуємо перевіряти статус перевірки власника та свіжість лістингу перед дзвінком.</p>"
            ),
            "related": [
                {"label": "Каталог єОселя", "href": f"{public_app_url()}?eoselya=1"},
                {"label": "Каталог агентств", "href": "/agencies"},
            ],
        },
        {
            "slug": "city-price-dynamics",
            "category": "Аналітика міст",
            "title": f"Цінова динаміка: що відбувається на ринку {top_city['city'] if top_city else 'України'}",
            "excerpt": (
                f"Середня ціна у {top_city['city']} становить ${int(top_city['avg_price']):,} за об'єкт при {top_city['cnt']} активних лістингах."
                if top_city
                else "Огляд активності в ключових регіонах з агрегацією цін по районах."
            ),
            "published_at": "2026-08-10",
            "reading_time": 5,
            "featured": True,
            "stats": [
                {"label": "Лідер за обсягом", "value": top_city["city"] if top_city else "Україна"},
                {"label": "Сер. ціна", "value": f"${int(top_city['avg_price']):,}" if top_city else "—"},
            ],
            "body_html": (
                f"<p>Ринок рухається у бік прозорих цін і швидких угод. У {top_city['city'] if top_city else 'топ-містах'} "
                "найбільший попит спостерігається на 1-2 кімнатні квартири зі свіжим підтвердженням активності.</p>"
            ),
            "related": [
                {"label": f"SEO-сторінка {top_city['city'] if top_city else ''}", "href": f"/seo/{quote(top_city['city'])}" if top_city else "/seo/Київ"},
                {"label": "Всі міста", "href": "/seo/snippets/top"},
            ],
        },
        {
            "slug": "agency-reputation-framework",
            "category": "Довіра та репутація",
            "title": "Рейтинг агентств UA-Dim: за якими метриками обирати рієлтора",
            "excerpt": (
                f"Лідер рейтингу — {top_agency['name']} (Score: {top_agency['reputation_score']}/100, verified-rate: {top_agency['verified_rate']:.1f}%)."
                if top_agency
                else "Як прозорий рейтинг відсікає фейки та піднімає агентства з верифікованою базою."
            ),
            "published_at": "2026-08-05",
            "reading_time": 3,
            "featured": False,
            "stats": [
                {"label": "Топ-партнер", "value": top_agency["name"] if top_agency else "—"},
                {"label": "Verified rate лідера", "value": f"{top_agency['verified_rate']:.1f}%" if top_agency else "—"},
            ],
            "body_html": (
                "<p>Ми розраховуємо репутацію агентства на базі 4 вимірних параметрів: verified-rate, SLA відповіді на лід, індекс свіжості та відсоток модераційного схвалення.</p>"
                "<p>Це унеможливлює накрутку відгуків і показує реальну операційну дисципліну команди.</p>"
            ),
            "related": [
                {"label": "Каталог агентств", "href": "/agencies"},
                {"label": "Рейтинг перевірених", "href": "/agencies?verified_only=1"},
            ],
        },
        {
            "slug": "freshness-and-anti-fake",
            "category": "Безпека",
            "title": "Антифейк та свіжість 14 днів: чому неактуальні лістинги втрачають видачу",
            "excerpt": f"За останні 14 днів оновлено {freshness_count} оголошень. Алгоритм автоматично знижує позиції об'єктів без підтвердження.",
            "published_at": "2026-08-03",
            "reading_time": 3,
            "featured": False,
            "stats": [
                {"label": "Оновлено 14д", "value": freshness_count},
                {"label": "Верифіковано", "value": int(db.execute("SELECT COUNT(*) FROM listings WHERE status='published' AND (verified_owner=1 OR verified_phone=1 OR verified_docs=1)").fetchone()[0] or 0)},
            ],
            "body_html": (
                "<p>Окрема якість supply side — це коли користувач бачить свіжість, доказовість і низький ризик дубля ще до відкриття картки.</p>"
                "<p>Саме це ми підсвічуємо в SERP і використовуємо для ранжування довіри.</p>"
            ),
            "related": [
                {"label": "Переглянути видачу", "href": public_app_url()},
                {"label": "Ризик дубля", "href": f"{public_app_url()}?duplicateRisk=high"},
            ],
        },
        {
            "slug": "map-first-hotspots",
            "category": "Discovery",
            "title": f"Map-first discovery: {top_district['city'] if top_district else 'міські'} hotspot-и зараз",
            "excerpt": (
                f"Найактивніший район — {top_district['district']} у {top_district['city']} з {top_district['cnt']} оголошеннями."
                if top_district
                else "Карта як центральний сценарій пошуку: фокус на hotspots і локальній аналітиці."
            ),
            "published_at": "2026-08-01",
            "reading_time": 4,
            "featured": False,
            "stats": [
                {"label": "Hotspot район", "value": top_district["cnt"] if top_district else 0},
                {"label": "Міст", "value": len(city_rows)},
            ],
            "body_html": (
                f"<p>Коли карта стає ядром, discovery перестає бути списком і перетворюється на локальну аналітику попиту.</p>"
                f"<p>Ми використовуємо місто/район/агенцію/свіжість як концентрат сигналів для навігації.</p>"
            ),
            "related": [
                {"label": "У карту", "href": f"{public_app_url()}?view=map"},
                {"label": "Топ-місто", "href": f"/seo/{quote(top_district['city'])}" if top_district else public_app_url()},
            ],
        },
    ]

    return articles


def _content_article_by_slug(db: sqlite3.Connection, slug: str) -> dict | None:
    for article in _content_articles(db):
        if article["slug"] == slug:
            return article
    return None


# ─── Routes ──────────────────────────────────────────────────────────────────

@content_bp.route("/api/agencies", methods=["GET"])
def get_agencies():
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")
    strip = getattr(app_module, "strip")
    truthy_flag = getattr(app_module, "truthy_flag")
    nonneg_int = getattr(app_module, "nonneg_int")

    db = get_db()
    args = request.args
    city = strip(args.get("city", ""), 100)
    kind = strip(args.get("kind", ""), 20).lower()
    verified_only = truthy_flag(args.get("verified_only"))
    q = strip(args.get("q", ""), 80)
    sort_by = strip(args.get("sort", "reputation"), 32).lower()
    limit = nonneg_int(args.get("limit")) or 30
    limit = min(max(limit, 1), 100)
    filters = ["ap.status = 'active'"]
    params: list = []
    if verified_only:
        filters.append("ap.is_verified = 1")
    if city:
        filters.append("ap.city = ?")
        params.append(city)
    if kind in {"agency", "developer"}:
        filters.append("ap.kind = ?")
        params.append(kind)
    if q:
        filters.append("(ap.name LIKE ? OR ap.specialization LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    return jsonify(agencies=_agency_metrics(db, where_sql, tuple(params), sort_by=sort_by, limit=limit))


@content_bp.route("/agencies", methods=["GET"])
def agencies_catalog_page():
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")
    strip = getattr(app_module, "strip")
    truthy_flag = getattr(app_module, "truthy_flag")
    public_app_url = getattr(app_module, "public_app_url", lambda: "/")

    db = get_db()
    city = strip(request.args.get("city", ""), 100)
    kind = strip(request.args.get("kind", ""), 20).lower()
    verified_only = truthy_flag(request.args.get("verified_only"))
    sort_by = strip(request.args.get("sort", "reputation"), 32).lower()
    q = strip(request.args.get("q", ""), 80)
    filters = ["ap.status = 'active'"]
    params: list = []
    if verified_only:
        filters.append("ap.is_verified = 1")
    if city:
        filters.append("ap.city = ?")
        params.append(city)
    if kind in {"agency", "developer"}:
        filters.append("ap.kind = ?")
        params.append(kind)
    if q:
        filters.append("(ap.name LIKE ? OR ap.specialization LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    agencies = _agency_metrics(db, where_sql, tuple(params), sort_by=sort_by, limit=100)
    cards_html = "".join(
        f"""
        <article style="border:1px solid #dbeafe;background:#f8fbff;border-radius:14px;padding:14px">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
            <div>
              <h3 style="margin:0 0 4px;font-size:18px">{html.escape(item["name"])}</h3>
              <p style="margin:0;color:#475569">{'Агентство' if item["kind"] == 'agency' else 'Забудовник'} · {html.escape(item["city"])} · Команда: {item["team_size"]}</p>
            </div>
            <span style="padding:6px 10px;border-radius:999px;background:#dbeafe;color:#1d4ed8;font-weight:700">Рейтинг {item["reputation_tier"]} · {item["reputation_score"]}/100</span>
          </div>
          <p style="margin:8px 0 10px;color:#334155">{html.escape(item["specialization"] or 'Нерухомість і супровід угод')}</p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px">
            <span style="font-size:12px;padding:5px 8px;border:1px solid #bfdbfe;background:#eff6ff;border-radius:10px">Активні: {item["active_listings"]}</span>
            <span style="font-size:12px;padding:5px 8px;border:1px solid #bbf7d0;background:#f0fdf4;border-radius:10px">Verified-rate: {item["verified_rate"]:.1f}%</span>
            <span style="font-size:12px;padding:5px 8px;border:1px solid #fde68a;background:#fffbeb;border-radius:10px">SLA відповіді: {item["avg_response_minutes"] or '—'} хв</span>
            <span style="font-size:12px;padding:5px 8px;border:1px solid #e2e8f0;background:#f8fafc;border-radius:10px">Угод: {item["completed_deals"]}</span>
          </div>
          <a href="/agencies/{quote(item["slug"])}" style="display:inline-block;padding:8px 12px;border-radius:10px;background:#0f172a;color:#fff;text-decoration:none;font-weight:600">Відкрити профіль</a>
        </article>
        """
        for item in agencies
    ) or '<p style="color:#64748b">Нічого не знайдено за фільтрами.</p>'
    html_page = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Каталог агентств і забудовників — UA Dim</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:1060px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:20px">
  <a href="{public_app_url()}" style="color:#2563eb;text-decoration:none">← До каталогу нерухомості</a>
  <h1 style="margin:12px 0 4px">Каталог агентств / забудовників</h1>
  <p style="margin:0 0 14px;color:#475569">Рейтинг за репутацією, trust-якістю, швидкістю відповіді та свіжістю активних оголошень.</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:0 0 16px">
    <div style="border:1px solid #dbeafe;background:#eff6ff;border-radius:12px;padding:10px"><b>{len(agencies)}</b><div style="color:#475569">Профілів</div></div>
    <div style="border:1px solid #dcfce7;background:#f0fdf4;border-radius:12px;padding:10px"><b>{sum(1 for item in agencies if item['is_verified'])}</b><div style="color:#475569">Верифікованих</div></div>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:10px"><b>{sum(item['active_listings'] for item in agencies)}</b><div style="color:#475569">Активних оголошень</div></div>
    <div style="border:1px solid #fef3c7;background:#fffbeb;border-radius:12px;padding:10px"><b>{round(sum(item['reputation_score'] for item in agencies)/len(agencies),1) if agencies else 0}</b><div style="color:#475569">Середній репутаційний score</div></div>
  </div>
  <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px">{cards_html}</section>
</main></body></html>"""
    return Response(html_page, mimetype="text/html")


@content_bp.route("/api/agencies/<slug>", methods=["GET"])
def get_agency_profile(slug: str):
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")
    listing_select = getattr(app_module, "LISTING_SELECT")
    row_to_listing = getattr(app_module, "_row_to_listing")

    db = get_db()
    metrics = _agency_metrics(
        db, "WHERE ap.slug = ? AND ap.status = 'active'", (slug,)
    )
    if not metrics:
        return jsonify(error="Агентство/забудовника не знайдено"), 404
    profile = metrics[0]
    listing_rows = db.execute(
        listing_select + " WHERE l.status = 'published' AND l.agency_slug = ? ORDER BY l.created_at DESC LIMIT 12",
        (slug,),
    ).fetchall()
    profile["listings"] = [row_to_listing(r) for r in listing_rows]
    return jsonify(profile=profile)


@content_bp.route("/agencies/<slug>", methods=["GET"])
def agency_profile_page(slug: str):
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")

    db = get_db()
    metrics = _agency_metrics(
        db, "WHERE ap.slug = ? AND ap.status = 'active'", (slug,)
    )
    if not metrics:
        return Response("<h1>Профіль не знайдено</h1>", status=404, mimetype="text/html")
    profile = metrics[0]
    listing_rows = db.execute(
        "SELECT id, title, city, district, price FROM listings WHERE status='published' AND agency_slug=? ORDER BY created_at DESC LIMIT 10",
        (slug,),
    ).fetchall()
    listing_items = "".join(
        f'<li><a href="/listing/{row["id"]}" style="color:#1d4ed8;text-decoration:none">{html.escape(row["title"])}</a>'
        f' <span style="color:#64748b">({html.escape(row["city"])}, {html.escape(row["district"])}) — ${int(row["price"]):,}</span></li>'
        for row in listing_rows
    ) or "<li>Поки немає активних оголошень</li>"
    kind_label = "Агентство" if profile["kind"] == "agency" else "Забудовник"
    verified_label = "Перевірено" if profile["is_verified"] else "Не перевірено"
    trust_text = {
        "A+": "Високий рівень довіри",
        "A": "Сильний рівень довіри",
        "B": "Стабільний рівень довіри",
        "C": "Базовий рівень довіри",
    }.get(profile["reputation_tier"], "Рівень довіри уточнюється")
    html_page = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(profile["name"])} — UA Dim</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:920px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:24px">
  <a href="/agencies" style="color:#2563eb;text-decoration:none">← До каталогу агентств</a>
  <h1 style="margin:14px 0 8px">{html.escape(profile["name"])}</h1>
  <p style="margin:0 0 8px;color:#475569">{kind_label} · {html.escape(profile["city"])} · {verified_label}</p>
  <p style="margin:0 0 16px;color:#1e3a8a;font-weight:600">Репутація: {profile["reputation_tier"]} ({profile["reputation_score"]}/100) · {trust_text}</p>
  <p style="margin:0 0 16px;color:#334155">{html.escape(profile["specialization"])}</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px">
    <div style="border:1px solid #dbeafe;background:#eff6ff;border-radius:12px;padding:12px"><b>{profile["active_listings"]}</b><div style="color:#475569">Активні оголошення</div></div>
    <div style="border:1px solid #dcfce7;background:#f0fdf4;border-radius:12px;padding:12px"><b>{profile["verified_rate"]:.1f}%</b><div style="color:#475569">Verified-rate</div></div>
    <div style="border:1px solid #fef3c7;background:#fffbeb;border-radius:12px;padding:12px"><b>{profile["avg_response_minutes"] or "—"} хв</b><div style="color:#475569">Середній час відповіді</div></div>
    <div style="border:1px solid #ede9fe;background:#f5f3ff;border-radius:12px;padding:12px"><b>{profile["team_size"]}</b><div style="color:#475569">Команда</div></div>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px"><b>{profile["completed_deals"]}</b><div style="color:#475569">Закриті угоди</div></div>
    <div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px"><b>{html.escape(profile["last_verified_at"] or "—")}</b><div style="color:#475569">Остання перевірка</div></div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px">
    <span style="font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid #bfdbfe;background:#eff6ff">Quality score: {profile["reputation_score"]}/100</span>
    <span style="font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid #bbf7d0;background:#f0fdf4">Moderation approve-rate: {profile["moderation_rate"]:.1f}%</span>
    <span style="font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid #fde68a;background:#fffbeb">Freshness-index: {round(profile["freshness_index"], 1) if profile["freshness_index"] is not None else "—"} / 100</span>
  </div>
  <h2 style="margin:8px 0 10px">Актуальні оголошення</h2>
  <ul style="margin:0;padding-left:20px;line-height:1.7">{listing_items}</ul>
</main></body></html>"""
    return Response(html_page, mimetype="text/html")


@content_bp.route("/api/content", methods=["GET"])
def get_content_articles():
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")
    strip = getattr(app_module, "strip")
    nonneg_int = getattr(app_module, "nonneg_int")

    db = get_db()
    limit = nonneg_int(request.args.get("limit")) or 6
    limit = min(max(limit, 1), 12)
    category = strip(request.args.get("category", ""), 32)
    articles = _content_articles(db)
    if category:
        articles = [article for article in articles if article["category"].lower() == category.lower()]
    return jsonify(articles=articles[:limit], featured=[article for article in articles if article.get("featured")][:limit])


@content_bp.route("/insights", methods=["GET"])
def insights_hub():
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")
    public_app_url = getattr(app_module, "public_app_url", lambda: "/")

    db = get_db()
    articles = _content_articles(db)
    cards = "".join(
        f"""
        <article style="border:1px solid #e2e8f0;background:#fff;border-radius:16px;padding:16px">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:center">
            <span style="font-size:12px;font-weight:700;color:#2563eb;background:#eff6ff;padding:6px 10px;border-radius:999px">{html.escape(article["category"])}</span>
            <span style="font-size:12px;color:#64748b">{html.escape(article["published_at"])} · {article["reading_time"]} хв</span>
          </div>
          <h2 style="margin:10px 0 6px;font-size:20px">{html.escape(article["title"])}</h2>
          <p style="margin:0 0 12px;color:#475569">{html.escape(article["excerpt"])}</p>
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">
            {''.join(f'<span style="font-size:12px;padding:5px 8px;border-radius:10px;border:1px solid #dbeafe;background:#eff6ff">{html.escape(str(stat["label"]))}: {html.escape(str(stat["value"]))}</span>' for stat in article["stats"])}
          </div>
          <a href="/insights/{quote(article["slug"])}" style="color:#1d4ed8;font-weight:700;text-decoration:none">Читати →</a>
        </article>
        """
        for article in articles
    )
    featured = [article for article in articles if article.get("featured")]
    featured_html = "".join(
        f'<span style="display:inline-block;margin:4px 8px 4px 0;padding:6px 10px;border-radius:999px;background:#dbeafe;color:#1d4ed8;font-weight:700">{html.escape(article["title"])}</span>'
        for article in featured
    ) or "<span style='color:#64748b'>Немає featured контенту</span>"
    html_page = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Insights — UA-Dim</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:1100px;margin:0 auto">
  <a href="{public_app_url()}" style="color:#2563eb;text-decoration:none">← До каталогу</a>
  <h1 style="margin:12px 0 6px;font-size:36px">Market insights / контентна машина</h1>
  <p style="margin:0 0 14px;color:#475569">Сторінки оновлюються з ринкових даних: міста, райони, єОселя, trust та карта.</p>
  <div style="margin:0 0 18px">{featured_html}</div>
  <section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px">{cards}</section>
</main></body></html>"""
    return Response(html_page, mimetype="text/html")


@content_bp.route("/insights/<slug>", methods=["GET"])
def insight_article(slug: str):
    app_module = _get_app_module()
    get_db = getattr(app_module, "get_db")

    db = get_db()
    article = _content_article_by_slug(db, slug)
    if not article:
        return Response("<h1>Матеріал не знайдено</h1>", status=404, mimetype="text/html")
    related_html = "".join(
        f'<li><a href="{html.escape(link["href"])}" style="color:#1d4ed8;text-decoration:none">{html.escape(link["label"])}</a></li>'
        for link in article.get("related", [])
    )
    stats_html = "".join(
        f'<div style="border:1px solid #e2e8f0;background:#f8fafc;border-radius:12px;padding:12px"><b>{html.escape(str(stat["value"]))}</b><div style="color:#475569">{html.escape(str(stat["label"]))}</div></div>'
        for stat in article.get("stats", [])
    )
    html_page = f"""<!doctype html>
<html lang="uk"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(article["title"])} — UA-Dim Insights</title>
<body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f8fafc;margin:0;padding:24px;color:#0f172a">
<main style="max-width:920px;margin:0 auto;background:#fff;border:1px solid #e2e8f0;border-radius:16px;padding:24px">
  <a href="/insights" style="color:#2563eb;text-decoration:none">← До Insights</a>
  <div style="margin-top:10px;font-size:12px;font-weight:700;color:#2563eb;background:#eff6ff;display:inline-block;padding:6px 10px;border-radius:999px">{html.escape(article["category"])}</div>
  <h1 style="margin:12px 0 6px;font-size:34px">{html.escape(article["title"])}</h1>
  <p style="margin:0 0 12px;color:#64748b">{html.escape(article["published_at"])} · {article["reading_time"]} хв читання</p>
  <p style="margin:0 0 18px;color:#334155;font-size:18px">{html.escape(article["excerpt"])}</p>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:18px">{stats_html}</div>
  <article style="line-height:1.7;color:#334155">{article["body_html"]}</article>
  <h2 style="margin:20px 0 8px">Пов'язані переходи</h2>
  <ul style="margin:0;padding-left:20px;line-height:1.8">{related_html}</ul>
</main></body></html>"""
    return Response(html_page, mimetype="text/html")
