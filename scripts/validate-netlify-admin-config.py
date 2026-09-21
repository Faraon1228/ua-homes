#!/usr/bin/env python3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "netlify.toml"
ADMIN_ROOT = ROOT / "web" / "admin"
EDGE_FUNCTION_NAME = "api-proxy"
EDGE_FUNCTION_ROUTE = "/api/*"
RETIRED_API_BACKEND_FUNCTION_NAME = "retired-api-backend"
RETIRED_API_BACKEND_ROUTES = {"/api-backend", "/api-backend/*"}
EDGE_FUNCTIONS_DIR = "netlify/edge-functions"
EDGE_FUNCTION_PATH = ROOT / EDGE_FUNCTIONS_DIR / f"{EDGE_FUNCTION_NAME}.ts"
RETIRED_API_BACKEND_FUNCTION_PATH = (
    ROOT / EDGE_FUNCTIONS_DIR / f"{RETIRED_API_BACKEND_FUNCTION_NAME}.ts"
)
EDGE_PROXY_DOC_PATH = ROOT / "NETLIFY_EDGE_PROXY.md"
CLOUDFLARE_DOC_PATH = ROOT / "CLOUDFLARE_ORIGIN_PROTECTION.md"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parse_directives(policy):
    directives = {}
    for segment in policy.split(";"):
        tokens = segment.strip().split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    return directives


def parse_netlify_config(text):
    config = tomllib.loads(text)
    build = config.get("build", {})
    require(isinstance(build, dict), "root [build] config is missing")
    header_rules = {}
    for rule in config.get("headers", []):
        path = rule.get("for")
        values = rule.get("values", {})
        require(path, "header rule is missing its path")
        require(isinstance(values, dict), f"header rule {path!r} is missing values")
        header_rules[path] = values
    return build, header_rules, config.get("edge_functions", []), config.get("redirects", [])


def is_same_origin_asset(value):
    parsed = urlsplit(value)
    return not parsed.scheme and not parsed.netloc and not value.startswith("//")


class AdminShellParser(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.path = path

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        for name, _value in attrs:
            require(name != "style", f"{self.path}: inline style attribute is not CSP-safe")
            require(
                not name.lower().startswith("on"),
                f"{self.path}: inline event handler {name!r} is not CSP-safe",
            )

        if tag == "style":
            raise AssertionError(f"{self.path}: inline <style> is not CSP-safe")
        if tag == "script":
            src = attributes.get("src")
            require(src, f"{self.path}: inline <script> is not CSP-safe")
            require(is_same_origin_asset(src), f"{self.path}: external script {src!r}")
        if tag == "link" and "stylesheet" in attributes.get("rel", "").split():
            href = attributes.get("href", "")
            require(is_same_origin_asset(href), f"{self.path}: external stylesheet {href!r}")


def validate_edge_api_proxy(build, edge_functions, redirects):
    require(
        build.get("edge_functions") == EDGE_FUNCTIONS_DIR,
        "Netlify build config must load checked-in edge functions",
    )
    require(
        any(
            rule.get("path") == EDGE_FUNCTION_ROUTE
            and rule.get("function") == EDGE_FUNCTION_NAME
            for rule in edge_functions
        ),
        "api-proxy edge function must route /api/*",
    )
    require(
        all(rule.get("from") != EDGE_FUNCTION_ROUTE for rule in redirects),
        "conflicting /api/* redirect must not coexist with the edge proxy",
    )
    require(
        all(not str(rule.get("from", "")).startswith("/api-backend") for rule in redirects),
        "retired /api-backend/* must not be configured as a redirect or origin proxy",
    )
    retired_routes = {
        rule.get("path")
        for rule in edge_functions
        if rule.get("function") == RETIRED_API_BACKEND_FUNCTION_NAME
    }
    require(
        RETIRED_API_BACKEND_ROUTES.issubset(retired_routes),
        "retired-api-backend edge function must route both /api-backend and /api-backend/*",
    )

    edge_proxy = EDGE_FUNCTION_PATH.read_text(encoding="utf-8")
    require(
        re.search(r'Netlify\.env\.get\("UA_HOMES_EDGE_TOKEN"\)\?\.trim\(\)', edge_proxy),
        "api-proxy must read the edge token from a Netlify secret",
    )
    require(
        'headers.set("X-UA-Edge-Token", edgeToken)' in edge_proxy,
        "api-proxy must forward the edge token to Railway",
    )
    require(
        'code: "edge_not_configured"' in edge_proxy and "{ status: 503 }" in edge_proxy,
        "api-proxy must fail closed when its edge token is absent",
    )
    require(
        "incoming.pathname + incoming.search" in edge_proxy,
        "api-proxy must preserve API paths and query strings",
    )
    require(
        re.search(r"export const config:\s*Config\s*=\s*\{[\s\S]*path:\s*\"/api/\*\"", edge_proxy),
        "api-proxy source config must declare the /api/* route",
    )
    retired_api_backend = RETIRED_API_BACKEND_FUNCTION_PATH.read_text(encoding="utf-8")
    require(
        "legacy_api_backend_retired" in retired_api_backend
        and "status: 410" in retired_api_backend,
        "retired-api-backend must return an explicit 410 JSON retirement response",
    )
    require(
        "fetch(" not in retired_api_backend and "railway.app" not in retired_api_backend.lower(),
        "retired-api-backend must not forward to Railway or any origin",
    )
    require(
        re.search(
            r"export const config:\s*Config\s*=\s*\{[\s\S]*\"/api-backend\"[\s\S]*\"/api-backend/\*\"",
            retired_api_backend,
        ),
        "retired-api-backend source config must declare both legacy routes",
    )

    edge_doc = EDGE_PROXY_DOC_PATH.read_text(encoding="utf-8")
    require(
        str(EDGE_FUNCTION_PATH.relative_to(ROOT)) in edge_doc,
        "Netlify edge proxy documentation must name the api-proxy source",
    )
    require(
        "UA_HOMES_EDGE_TOKEN" in edge_doc and "edge_not_configured" in edge_doc,
        "Netlify edge proxy documentation must cover secret setup and fail-closed behavior",
    )
    require(
        "old unauthenticated" in edge_doc and "removed" in edge_doc,
        "Netlify edge proxy documentation must record that the legacy /api/* redirect is removed",
    )
    require(
        str(RETIRED_API_BACKEND_FUNCTION_PATH.relative_to(ROOT)) in edge_doc
        and "legacy_api_backend_retired" in edge_doc,
        "Netlify edge proxy documentation must describe retired /api-backend/* behavior",
    )
    cloudflare_doc = CLOUDFLARE_DOC_PATH.read_text(encoding="utf-8")
    require(
        "NETLIFY_EDGE_PROXY.md" in cloudflare_doc,
        "Cloudflare origin-protection documentation must point to the active Netlify proxy",
    )


def validate_admin_shells():
    for path in (ADMIN_ROOT / "login.html", ADMIN_ROOT / "dashboard.html"):
        parser = AdminShellParser(path.relative_to(ROOT))
        parser.feed(path.read_text(encoding="utf-8"))

    style_prop = re.compile(r"\bstyle\s*=")
    for pattern in ("*.js", "*.jsx"):
        for path in (ADMIN_ROOT / "src").rglob(pattern):
            require(
                not style_prop.search(path.read_text(encoding="utf-8")),
                f"{path.relative_to(ROOT)}: React inline style is not CSP-safe",
            )


def main():
    require(
        not (ADMIN_ROOT / "netlify.toml").exists(),
        "web/admin/netlify.toml is ignored by the canonical root deploy and must not return",
    )

    config_text = CONFIG_PATH.read_text(encoding="utf-8")
    build, header_rules, edge_functions, redirects = parse_netlify_config(config_text)
    require(build.get("publish") == "web", "root deploy must publish web/")
    validate_edge_api_proxy(build, edge_functions, redirects)
    require("/*" in header_rules, "public fallback header rule is missing")
    require("/admin/*" in header_rules, "specific /admin/* header rule is missing")

    public_policy = header_rules["/*"].get("Content-Security-Policy", "")
    require("'unsafe-inline'" in public_policy, "public policy changed unexpectedly")
    require("https://www.liqpay.ua" in public_policy, "public payment policy changed")

    admin_headers = header_rules["/admin/*"]
    require(admin_headers.get("Cache-Control") == "no-store", "admin responses must not be cached")
    require(admin_headers.get("X-Frame-Options") == "DENY", "admin framing must be denied")

    admin_policy = admin_headers.get("Content-Security-Policy", "")
    directives = parse_directives(admin_policy)
    require(directives.get("script-src") == ["'self'"], "admin scripts must be self-hosted")
    require(directives.get("style-src") == ["'self'"], "admin styles must be self-hosted")
    require(
        directives.get("connect-src")
        == [
            "'self'",
            "https://*.ingest.sentry.io",
            "https://*.ingest.us.sentry.io",
            "https://*.ingest.de.sentry.io",
        ],
        "admin connections must be limited to same-origin and Sentry ingestion",
    )
    require(directives.get("object-src") == ["'none'"], "admin objects must be disabled")
    require(directives.get("frame-ancestors") == ["'none'"], "admin framing must be disabled")
    for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "unpkg.com", "cdn.tailwindcss.com"):
        require(forbidden not in admin_policy, f"admin policy contains forbidden source {forbidden}")

    validate_admin_shells()
    print("Netlify admin CSP and API edge proxy contracts are valid.")


if __name__ == "__main__":
    main()
