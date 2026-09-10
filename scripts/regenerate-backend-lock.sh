#!/usr/bin/env bash
# Regenerates backend/requirements.lock.txt with pinned versions and SHA-256
# hashes for every dependency, matching the Python version used in CI and
# Railway production (3.12). Run this after editing backend/requirements.txt.
#
# Requires Docker so the resolved hashes match the linux/amd64 wheels that
# CI and Railway actually install (running pip-compile on macOS/arm64 would
# resolve different, incompatible wheel hashes).
set -euo pipefail

cd "$(dirname "$0")/.."

docker run --rm --platform linux/amd64 \
  -v "$PWD/backend":/work -w /work \
  -e PIP_DEFAULT_TIMEOUT=120 \
  python:3.12-slim bash -c '
    pip install --quiet --upgrade pip pip-tools &&
    pip-compile --generate-hashes --allow-unsafe \
      --output-file=requirements.lock.txt requirements.txt &&
    pip install --quiet --require-hashes -r requirements.lock.txt &&
    python -c "import flask, gunicorn, psycopg2, redis, boto3, cloudinary, PIL, sentry_sdk, firebase_admin; print(\"lock file installs cleanly\")"
  '

echo "backend/requirements.lock.txt regenerated. Review the diff, then commit both requirements.txt (if changed) and requirements.lock.txt together."
