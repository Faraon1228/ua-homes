from __future__ import annotations

import os
import re
from collections.abc import Mapping
from urllib.parse import urlsplit


DEFAULT_CORS_ORIGINS: tuple[str | re.Pattern[str], ...] = (
    re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"),
    re.compile(r"^https://(localhost|127\.0\.0\.1)(:\d+)?$"),
    "https://ua-homes.netlify.app",
    "https://ua-dim.netlify.app",
    "https://ua-dom.com",
    "https://www.ua-dom.com",
    "https://ua-dim.com",
    "https://www.ua-dim.com",
)

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def response_security_headers(*, is_secure: bool, is_html: bool) -> dict[str, str]:
    headers = dict(SECURITY_HEADERS)
    if is_secure:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if is_html:
        headers["Content-Security-Policy"] = ""
    return headers


def cors_origins(
    environment: Mapping[str, str] | None = None,
) -> list[str | re.Pattern[str]]:
    environment = os.environ if environment is None else environment
    configured = environment.get("UA_HOMES_CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    origins = list(DEFAULT_CORS_ORIGINS)
    if environment.get(
        "UA_HOMES_ALLOW_NETLIFY_PREVIEW_CORS", ""
    ).strip().lower() in {"1", "true", "yes"}:
        origins.append(re.compile(r"^https://[a-z0-9-]+\.netlify\.app$"))
    return origins


def build_html_csp(public_site_url: str = "", api_origin: str = "") -> str:
    connect_sources = [
        "'self'",
        "https://api.cloudinary.com",
        "https://res.cloudinary.com",
        "https://*.amazonaws.com",
        "https://*.cloudfront.net",
    ]
    if public_site_url:
        parsed_public_url = urlsplit(public_site_url)
        if parsed_public_url.scheme and parsed_public_url.netloc:
            connect_sources.append(
                f"{parsed_public_url.scheme}://{parsed_public_url.netloc}"
            )
    if api_origin:
        connect_sources.append(api_origin)

    return (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "img-src 'self' data: blob: https://res.cloudinary.com https://*.amazonaws.com https://*.cloudfront.net https://images.unsplash.com https://picsum.photos https://fastly.picsum.photos https://*.tile.openstreetmap.org; "
        "media-src 'self' blob: https://res.cloudinary.com https://*.amazonaws.com https://*.cloudfront.net; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com; "
        f"connect-src {' '.join(connect_sources)}; "
        "font-src 'self' data:; "
        "worker-src 'self' blob:; "
        "manifest-src 'self';"
    )
