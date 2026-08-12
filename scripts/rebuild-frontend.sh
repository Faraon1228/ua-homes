#!/bin/bash
# Recompile JSX → real-estate-app.js and regenerate purged ua-homes.css.
# Downloads esbuild and tailwindcss binaries on first run (macOS arm64 / amd64).
set -e

REPO_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
WEB_DIR="$REPO_DIR/web"
TOOLS_DIR="$REPO_DIR/tools"
mkdir -p "$TOOLS_DIR"

ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')

# ── esbuild binary ──
ESBUILD="$TOOLS_DIR/esbuild"
if [ ! -x "$ESBUILD" ]; then
  ESBUILD_VERSION="0.24.2"
  if [ "$ARCH" = "arm64" ]; then PKG="@esbuild/darwin-arm64"; else PKG="@esbuild/darwin-x64"; fi
  echo "⬇  Downloading esbuild ${ESBUILD_VERSION}..."
  curl -fsSL "https://registry.npmjs.org/${PKG}/-/${PKG##*/}-${ESBUILD_VERSION}.tgz" \
    | tar xz -C "$TOOLS_DIR" --strip-components=2 package/bin/esbuild
  chmod +x "$ESBUILD"
  echo "   ✅ esbuild ready"
fi

# ── tailwindcss standalone binary ──
TAILWIND="$TOOLS_DIR/tailwindcss"
if [ ! -x "$TAILWIND" ]; then
  if [ "$ARCH" = "arm64" ]; then SUFFIX="macos-arm64"; else SUFFIX="macos-x64"; fi
  TWVER="3.4.17"
  echo "⬇  Downloading tailwindcss ${TWVER}..."
  curl -fsSLo "$TAILWIND" \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TWVER}/tailwindcss-${SUFFIX}"
  chmod +x "$TAILWIND"
  echo "   ✅ tailwindcss ready"
fi

# ── compile source JSX ──
echo "🔨 Compiling JSX → real-estate-app.js ..."
"$ESBUILD" "$WEB_DIR/RealEstateApp.jsx" 2>/dev/null \
  --bundle --format=iife --jsx=transform --jsx-factory=React.createElement \
  --jsx-fragment=React.Fragment --target=es2020 --minify \
  --charset=utf8 --outfile="$WEB_DIR/real-estate-app.js" && echo "   ✅ real-estate-app.js compiled ($(wc -c < "$WEB_DIR/real-estate-app.js" | tr -d ' ') bytes)"

# ── generate purged Tailwind CSS ──
echo "🎨 Generating purged ua-homes.css ..."
cat > /tmp/tw-input.css <<'CSS'
@tailwind base;
@tailwind components;
@tailwind utilities;
CSS
cat "$WEB_DIR/ua-dim-modern.css" >> /tmp/tw-input.css

cat > /tmp/tw-config.js <<JS
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
# Expand variable inside heredoc
sed -i '' "s|\${WEB_DIR}|${WEB_DIR}|g" /tmp/tw-config.js

"$TAILWIND" -i /tmp/tw-input.css -o "$WEB_DIR/ua-homes.css" \
  --config /tmp/tw-config.js --minify 2>&1 | grep -v "^Browserslist"

echo "   ✅ ua-homes.css ($(wc -c < "$WEB_DIR/ua-homes.css" | tr -d ' ') bytes)"
echo ""
echo "✅  Frontend build complete."
