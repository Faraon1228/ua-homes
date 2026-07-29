#!/bin/bash

# 🏠 UA Homes - Run Locally Script
# Запустіть цей скрипт для локального тестування UA Homes

set -e

echo "╔════════════════════════════════════════════╗"
echo "║   🏠 UA HOMES - LOCAL DEVELOPMENT RUN     ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Визначимо кореневу директорію проекту
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_DIR"

echo "📁 Project directory: $PROJECT_DIR"
echo ""

# Перевіримо, чи встановлено Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не знайдено. Встановіть Python3 і спробуйте ще раз."
    exit 1
fi

echo "✅ Python3 знайдено"
echo ""

# Запуск бекенду
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "BACKEND SETUP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -d "backend" ]; then
    echo "❌ backend/ папка не знайдена!"
    exit 1
fi

cd backend

# Перевіримо залежності
if [ ! -f "requirements.txt" ]; then
    echo "❌ requirements.txt не знайдено!"
    exit 1
fi

echo "📦 Installing Python dependencies..."
if python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
    echo "✅ Dependencies installed"
else
    echo "⚠️  pip module is not available; skipping dependency install"
    echo "   Make sure dependencies are installed in your Python environment."
fi
echo ""

# Запускаємо Flask сервер
echo "🚀 Starting Flask backend on port 5050..."
python3 app.py &
BACKEND_PID=$!
echo "✅ Backend started (PID: $BACKEND_PID)"
sleep 2

# Перевіримо, чи запустився бекенд
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "❌ Backend failed to start!"
    exit 1
fi

cd "$PROJECT_DIR"
echo ""

# Запуск фронтенду
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "FRONTEND SETUP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -d "web" ]; then
    echo "❌ web/ папка не знайдена!"
    exit 1
fi

cd web

# Rebuild compiled JS and purged CSS if esbuild/tailwind binaries are available
ESBUILD_BIN=""
TAILWIND_BIN=""
for p in /tmp/esbuild "$PROJECT_DIR/tools/esbuild" "$(which esbuild 2>/dev/null)"; do
  [ -x "$p" ] && ESBUILD_BIN="$p" && break
done
for p in /tmp/tailwindcss "$PROJECT_DIR/tools/tailwindcss" "$(which tailwindcss 2>/dev/null)"; do
  [ -x "$p" ] && TAILWIND_BIN="$p" && break
done

if [ -n "$ESBUILD_BIN" ] && [ -f "../web/real-estate-app.js" ]; then
  echo "🔨 Skipping JSX recompile (compiled file present). Run scripts/rebuild-frontend.sh to force."
elif [ -n "$ESBUILD_BIN" ]; then
  echo "🔨 Compiling JSX → real-estate-app.js ..."
  python3 - <<'PYEOF'
import re
with open('../web/real-estate-demo.html') as f: html = f.read()
m = re.search(r'<script type="text/babel">(.*?)</script>', html, re.DOTALL)
if m:
    open('/tmp/ua-homes-app.jsx','w').write(m.group(1))
PYEOF
  "$ESBUILD_BIN" /tmp/ua-homes-app.jsx \
    --bundle=false --jsx=transform --jsx-factory=React.createElement \
    --jsx-fragment=React.Fragment --target=es2020 --minify-whitespace \
    --charset=utf8 --outfile=real-estate-app.js 2>&1 && echo "  ✅ real-estate-app.js compiled"
fi

if [ -n "$TAILWIND_BIN" ] && [ ! -f "ua-homes.css" ]; then
  echo "🎨 Generating purged Tailwind CSS ..."
  "$TAILWIND_BIN" \
    -i /dev/null -o ua-homes.css \
    --content "./real-estate-demo.html,./real-estate-app.js" \
    --minify 2>&1 | tail -1 && echo "  ✅ ua-homes.css generated"
fi

echo "🌐 Starting HTTP server on port 8080..."
python3 -m http.server 8080 &
FRONTEND_PID=$!
echo "✅ Frontend started (PID: $FRONTEND_PID)"
sleep 1

cd "$PROJECT_DIR"
echo ""

# Останні інструкції
echo "╔════════════════════════════════════════════╗"
echo "║          ✅ ALL SERVICES RUNNING          ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "📱 Frontend:  http://localhost:8080/real-estate-demo.html"
echo "⚙️  Backend:   http://localhost:5050"
echo ""
echo "💡 Tips:"
echo "   • Open Browser DevTools (F12) to see errors"
echo "   • Check Network tab for API calls"
echo "   • Backend logs appear below"
echo ""
echo "🛑 To stop all services, press Ctrl+C"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Очікуємо на Ctrl+C
trap "echo ''; echo '🛑 Shutting down services...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Done!'; exit 0" INT

wait
