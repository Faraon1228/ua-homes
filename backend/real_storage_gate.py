"""Safety gate for the opt-in real Cloudinary storage test.

The test environment must be identified explicitly: UA_TEST_CLOUDINARY_URL plus
UA_TEST_CLOUDINARY_CONFIRM (the expected cloud name). The gate fails closed on any
mismatch and never returns or logs credential values.

Values come from the process environment or from the single, explicitly named,
gitignored file ``.env.test.local`` in the repository root (plain KEY=VALUE lines;
it is parsed, never sourced or evaluated).
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

ENV_FILE_NAME = ".env.test.local"
ALLOWED_KEYS = ("UA_TEST_CLOUDINARY_URL", "UA_TEST_CLOUDINARY_CONFIRM")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_env_file(path: str | None = None) -> dict[str, str]:
    path = path or os.path.join(REPO_ROOT, ENV_FILE_NAME)
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key in ALLOWED_KEYS:
                    values[key] = value.strip().strip("'\"")
    except OSError:
        pass
    return values


def cloud_name_of(url: str) -> str:
    """Cloud name of a cloudinary://key:secret@cloud URL, or '' if malformed."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    if parts.scheme != "cloudinary" or not parts.username or not parts.password:
        return ""
    return (parts.hostname or "").lower()


def production_cloud_names(environment=None) -> set[str]:
    environment = os.environ if environment is None else environment
    names = {cloud_name_of(environment.get("CLOUDINARY_URL", ""))}
    names.add((environment.get("CLOUDINARY_CLOUD_NAME") or "").strip().lower())
    return {name for name in names if name}


def resolve(environment=None, file_values: dict[str, str] | None = None) -> tuple[str, str]:
    """Return (test_cloudinary_url, "") when safe, otherwise ("", reason)."""
    environment = os.environ if environment is None else environment
    file_values = read_env_file() if file_values is None else file_values

    def pick(key: str) -> str:
        return (environment.get(key) or file_values.get(key) or "").strip()

    url, confirm = pick("UA_TEST_CLOUDINARY_URL"), pick("UA_TEST_CLOUDINARY_CONFIRM").lower()
    if not url or not confirm:
        return "", "UA_TEST_CLOUDINARY_URL and UA_TEST_CLOUDINARY_CONFIRM are not both set"
    cloud = cloud_name_of(url)
    if not cloud:
        return "", "UA_TEST_CLOUDINARY_URL is not a valid cloudinary://key:secret@cloud URL"
    if not re.fullmatch(r"[a-z0-9_-]+", confirm) or cloud != confirm:
        return "", "UA_TEST_CLOUDINARY_CONFIRM does not match the cloud name in UA_TEST_CLOUDINARY_URL"
    if cloud in production_cloud_names(environment):
        return "", "test cloud name equals a known production cloud reference; refusing to run"
    return url, ""
