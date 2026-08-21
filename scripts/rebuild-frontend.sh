#!/bin/bash
# Recompile JSX → real-estate-app.js and regenerate purged ua-homes.css.
# Downloads pinned esbuild and tailwindcss binaries on first run.
set -euo pipefail

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
WEB_DIR="$REPO_DIR/web"
TOOLS_DIR="$REPO_DIR/tools"
mkdir -p "$TOOLS_DIR"

ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$OS-$ARCH" in
  darwin-arm64)
    ESBUILD_PLATFORM="darwin-arm64"
    TAILWIND_PLATFORM="macos-arm64"
    ;;
  darwin-x86_64)
    ESBUILD_PLATFORM="darwin-x64"
    TAILWIND_PLATFORM="macos-x64"
    ;;
  linux-aarch64|linux-arm64)
    ESBUILD_PLATFORM="linux-arm64"
    TAILWIND_PLATFORM="linux-arm64"
    ;;
  linux-x86_64)
    ESBUILD_PLATFORM="linux-x64"
    TAILWIND_PLATFORM="linux-x64"
    ;;
  *)
    echo "Unsupported frontend build platform: $OS-$ARCH" >&2
    exit 1
    ;;
esac

# ── esbuild binary ──
ESBUILD="$TOOLS_DIR/esbuild"
if [ -x "$ESBUILD" ] && ! "$ESBUILD" --version >/dev/null 2>&1; then
  rm -f "$ESBUILD"
fi
if [ ! -x "$ESBUILD" ]; then
  ESBUILD_VERSION="0.24.2"
  PKG="@esbuild/$ESBUILD_PLATFORM"
  echo "⬇  Downloading esbuild ${ESBUILD_VERSION}..."
  curl -fsSL "https://registry.npmjs.org/${PKG}/-/${PKG##*/}-${ESBUILD_VERSION}.tgz" \
    | tar xz -C "$TOOLS_DIR" --strip-components=2 package/bin/esbuild
  chmod +x "$ESBUILD"
  echo "   ✅ esbuild ready"
fi

# ── tailwindcss standalone binary ──
TAILWIND="$TOOLS_DIR/tailwindcss"
if [ -x "$TAILWIND" ] && ! "$TAILWIND" --help >/dev/null 2>&1; then
  rm -f "$TAILWIND"
fi
if [ ! -x "$TAILWIND" ]; then
  TWVER="3.4.17"
  echo "⬇  Downloading tailwindcss ${TWVER}..."
  curl -fsSLo "$TAILWIND" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TWVER}/tailwindcss-${TAILWIND_PLATFORM}"
  chmod +x "$TAILWIND"
  echo "   ✅ tailwindcss ready"
fi

# ── compile source JSX ──
echo "🔨 Compiling JSX → real-estate-app.js + lazy chunks ..."
rm -rf "$WEB_DIR/chunks"
"$ESBUILD" "$WEB_DIR/RealEstateApp.jsx" 2>/dev/null \
  --bundle --format=esm --splitting --jsx=transform --jsx-factory=React.createElement \
  --jsx-fragment=React.Fragment --target=es2020 --minify \
  --define:__UA_SELLER_BUILD__=false \
  --charset=utf8 --outdir="$WEB_DIR" --entry-names=real-estate-app \
  --chunk-names=chunks/[name]-[hash] && echo "   ✅ real-estate-app.js compiled ($(wc -c < "$WEB_DIR/real-estate-app.js" | tr -d ' ') bytes)"

"$ESBUILD" "$WEB_DIR/RealEstateApp.jsx" 2>/dev/null \
  --bundle --format=esm --splitting --jsx=transform --jsx-factory=React.createElement \
  --jsx-fragment=React.Fragment --target=es2020 --minify \
  --define:__UA_SELLER_BUILD__=true \
  --charset=utf8 --outdir="$WEB_DIR" --entry-names=seller-app \
  --chunk-names=chunks/[name]-[hash] && echo "   ✅ seller-app.js compiled ($(wc -c < "$WEB_DIR/seller-app.js" | tr -d ' ') bytes)"

CATALOG_BYTES=$(wc -c < "$WEB_DIR/real-estate-app.js" | tr -d ' ')
SELLER_BYTES=$(wc -c < "$WEB_DIR/seller-app.js" | tr -d ' ')
if [ "$CATALOG_BYTES" -gt 130000 ] || [ "$SELLER_BYTES" -gt 135000 ]; then
  echo "Frontend bundle budget exceeded: catalog=${CATALOG_BYTES}, seller=${SELLER_BYTES}" >&2
  exit 1
fi

# ── generate purged Tailwind CSS ──
echo "🎨 Generating purged ua-homes.css ..."
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ua-dim-frontend.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
TW_INPUT="$TMP_DIR/input.css"
TW_CONFIG="$TMP_DIR/config.js"

cat > "$TW_INPUT" <<'CSS'
@tailwind base;
@tailwind components;
@tailwind utilities;
CSS
cat "$WEB_DIR/ua-dim-modern.css" >> "$TW_INPUT"

cat > "$TW_CONFIG" <<JS
module.exports = {
  content: [
    '${WEB_DIR}/real-estate-demo.html',
    '${WEB_DIR}/real-estate-app.js',
    '${WEB_DIR}/RealEstateApp.jsx',
    '${WEB_DIR}/admin/dashboard.html',
  ],
  theme: { extend: {} },
  plugins: [],
}
JS

"$TAILWIND" -i "$TW_INPUT" -o "$WEB_DIR/ua-homes.css" \
  --config "$TW_CONFIG" --minify 2>&1 | sed '/^Browserslist/d'

echo "   ✅ ua-homes.css ($(wc -c < "$WEB_DIR/ua-homes.css" | tr -d ' ') bytes)"

BUILD_ID=$(
  {
    cat "$WEB_DIR/app-loader.js" "$WEB_DIR/real-estate-app.js" \
      "$WEB_DIR/seller-app.js" "$WEB_DIR/ua-homes.css" "$WEB_DIR/sw.js" \
      "$WEB_DIR/real-estate-demo.html" "$WEB_DIR/ua-homes-manifest.json" \
      "$WEB_DIR/privacy.html" "$WEB_DIR/terms.html" "$WEB_DIR/cookie-policy.html" \
      "$WEB_DIR/privacy-consent.css" "$WEB_DIR/privacy-consent.js" \
      "$WEB_DIR/vendor/react.production.min.js" \
      "$WEB_DIR/vendor/react-dom.production.min.js"
    find "$WEB_DIR/chunks" -type f -name '*.js' -print |
      sort |
      while IFS= read -r chunk; do
        cat "$chunk"
      done
  } | shasum -a 256 | cut -c1-12
)
{
  printf "self.__UA_BUILD_ID = '%s';\n" "$BUILD_ID"
  printf 'self.__UA_PRECACHE_ASSETS = [\n'
  printf "  '/precache-manifest.js',\n"
  printf "  '/',\n"
  printf "  '/app-loader.js',\n"
  printf "  '/real-estate-app.js',\n"
  printf "  '/seller-app.js',\n"
  printf "  '/ua-homes.css',\n"
  find "$WEB_DIR/chunks" -type f -name '*.js' -print |
    sort |
    sed "s#^$WEB_DIR#  '#; s#\$#',#"
  printf '];\n'
} > "$WEB_DIR/precache-manifest.js"

echo ""
echo "✅  Frontend build complete."
