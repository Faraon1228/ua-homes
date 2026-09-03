#!/usr/bin/env python3
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETLINKS_PATH = ROOT / "web" / ".well-known" / "assetlinks.json"
NETLIFY_PATH = ROOT / "netlify.toml"
EXPECTED_FINGERPRINTS = [
    "2B:A6:42:87:54:EA:BA:71:FB:0E:A2:1F:72:17:73:BE:52:88:C9:86:63:F3:0E:18:E1:12:12:27:2E:B2:2C:DE",
    "EE:11:9F:28:AB:1C:26:BD:34:D7:74:52:64:6D:2D:2B:51:BC:9C:DF:88:40:98:99:82:BF:F4:49:14:67:A4:72",
]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    statements = json.loads(ASSETLINKS_PATH.read_text(encoding="utf-8"))
    require(len(statements) == 1, "assetlinks.json must contain exactly one statement")

    statement = statements[0]
    require(
        statement == {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.uadim.app",
                "sha256_cert_fingerprints": EXPECTED_FINGERPRINTS,
            },
        },
        "assetlinks.json must authorize exactly the UA-Dim upload and Play signing certificates",
    )

    netlify = NETLIFY_PATH.read_text(encoding="utf-8")
    header_rule = re.search(
        r'(?ms)^\[\[headers\]\]\s*\n\s*for = "/\.well-known/assetlinks\.json"\s*\n'
        r"\s*\[headers\.values\]\s*\n\s*Content-Type = \"application/json\"\s*$",
        netlify,
    )
    require(header_rule, "assetlinks.json must be served as application/json")

    redirect_sources = re.findall(
        r'(?ms)^\[\[redirects\]\]\s*\n(.*?)(?=^\[\[|\Z)', netlify
    )
    require(
        all(
            not re.search(
                r'(?m)^\s*from\s*=\s*"/\.well-known/assetlinks\.json"\s*$',
                block,
            )
            for block in redirect_sources
        ),
        "assetlinks.json must be served directly without a redirect",
    )

    print("UA-Dim asset links authorize upload and Play signing certificates.")


if __name__ == "__main__":
    main()
