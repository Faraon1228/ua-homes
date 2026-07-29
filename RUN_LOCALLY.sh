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
