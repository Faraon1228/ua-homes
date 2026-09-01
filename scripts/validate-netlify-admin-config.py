#!/usr/bin/env python3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import ast
import re


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "netlify.toml"
ADMIN_ROOT = ROOT / "web" / "admin"


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


def parse_assignment(line):
    key, separator, raw_value = line.partition("=")
    require(separator, f"invalid Netlify assignment: {line!r}")
    return key.strip(), ast.literal_eval(raw_value.strip())


def parse_netlify_config(text):
    publish_match = re.search(
        r"(?ms)^\[build\]\s*$(.*?)(?=^\[|\Z)",
        text,
    )
    require(publish_match, "root [build] config is missing")
    publish = None
    for line in publish_match.group(1).splitlines():
        if line.strip().startswith("publish"):
            _key, publish = parse_assignment(line)

    header_rules = {}
    for block in re.split(r"(?m)^\[\[headers\]\]\s*$", text)[1:]:
        block = re.split(r"(?m)^\[\[", block, maxsplit=1)[0]
        path = None
        values = {}
        in_values = False
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "[headers.values]":
                in_values = True
                continue
            key, value = parse_assignment(stripped)
            if key == "for" and not in_values:
                path = value
            elif in_values:
                values[key] = value
        require(path, "header rule is missing its path")
        header_rules[path] = values
    return publish, header_rules


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

    publish, header_rules = parse_netlify_config(CONFIG_PATH.read_text(encoding="utf-8"))
    require(publish == "web", "root deploy must publish web/")
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
        == ["'self'", "https://*.ingest.sentry.io", "https://*.ingest.us.sentry.io"],
        "admin connections must be limited to same-origin and Sentry ingestion",
    )
    require(directives.get("object-src") == ["'none'"], "admin objects must be disabled")
    require(directives.get("frame-ancestors") == ["'none'"], "admin framing must be disabled")
    for forbidden in ("'unsafe-inline'", "'unsafe-eval'", "unpkg.com", "cdn.tailwindcss.com"):
        require(forbidden not in admin_policy, f"admin policy contains forbidden source {forbidden}")

    validate_admin_shells()
    print("Netlify admin CSP is specific, strict, and compatible with the admin bundle.")


if __name__ == "__main__":
    main()
