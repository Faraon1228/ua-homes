#!/bin/bash
set -euo pipefail

ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
cd "$ROOT"
cleanup() {
  find web -type f -name '*.map' -delete
  find web -type f -name '*.js' -exec sed -i.bak '/^\/\/# sourceMappingURL=.*\.map$/d' {} +
  find web -type f -name '*.js.bak' -delete
}
trap cleanup EXIT

if [ -z "${SENTRY_AUTH_TOKEN:-}" ]; then
  echo "Sentry source-map upload disabled; auth token is not configured."
  exit 0
fi
for name in SENTRY_ORG SENTRY_WEB_PROJECT SENTRY_ADMIN_PROJECT SENTRY_RELEASE; do
  if [ -z "${!name:-}" ]; then
    echo "Sentry source-map upload configuration is incomplete: $name is missing." >&2
    exit 1
  fi
done
if ! find web -type f -name '*.map' -print -quit | grep -q .; then
  echo "Sentry source maps were not generated." >&2
  exit 1
fi

PUBLIC_ASSETS=(web/real-estate-app.js web/seller-app.js web/monitoring.js web/chunks)
ADMIN_ASSETS=(web/admin/admin-app.js web/admin/login-app.js web/admin/monitoring.js web/admin/chunks)
npx --no-install sentry-cli sourcemaps inject "${PUBLIC_ASSETS[@]}" "${ADMIN_ASSETS[@]}"
npx --no-install sentry-cli sourcemaps upload \
  --org "$SENTRY_ORG" --project "$SENTRY_WEB_PROJECT" --release "$SENTRY_RELEASE" \
  --url-prefix '~/' --validate "${PUBLIC_ASSETS[@]}"
npx --no-install sentry-cli sourcemaps upload \
  --org "$SENTRY_ORG" --project "$SENTRY_ADMIN_PROJECT" --release "$SENTRY_RELEASE" \
  --url-prefix '~/admin/' --validate "${ADMIN_ASSETS[@]}"
echo "Uploaded Sentry source maps; local map files will be removed before packaging."
