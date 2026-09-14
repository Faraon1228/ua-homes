#!/usr/bin/env python3
"""Validate the checked-in Cloudflare Worker origin-protection contract."""

from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = ROOT / "cloudflare" / "ua-dim-api-worker.js"
WRANGLER_PATH = ROOT / "cloudflare" / "wrangler.toml"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    worker = WORKER_PATH.read_text(encoding="utf-8")
    config = tomllib.loads(WRANGLER_PATH.read_text(encoding="utf-8"))

    require(config.get("main") == WORKER_PATH.name, "Worker entrypoint is incorrect")
    routes = config.get("routes", [])
    patterns = {route.get("pattern") for route in routes}
    require(
        {"ua-dim.com/api/*", "www.ua-dim.com/api/*"} <= patterns,
        "Cloudflare must route both public domains' /api/* paths",
    )
    require(
        "UA_HOMES_EDGE_TOKEN" not in config.get("vars", {}),
        "Wrangler config must not contain an edge-token value",
    )
    require(
        re.search(r'pathname\.startsWith\("/api/"\)', worker),
        "Worker must limit proxying to /api/*",
    )
    require(
        re.search(r"env\.UA_HOMES_EDGE_TOKEN\?\.trim\(\)", worker),
        "Worker must read the edge token from a secret",
    )
    require(
        'headers.set("X-UA-Edge-Token", edgeToken)' in worker,
        "Worker must forward the edge token to Railway",
    )
    require(
        'code: "edge_not_configured"' in worker and "{ status: 503 }" in worker,
        "Worker must fail closed when its edge token is absent",
    )
    require(
        'incoming.pathname + incoming.search' in worker,
        "Worker must preserve API paths and query strings",
    )
    print("Cloudflare API Worker routes and secret forwarding are valid.")


if __name__ == "__main__":
    main()
