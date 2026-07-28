#!/bin/bash

# UA Homes - Mobile App Setup Script
# This script prepares the project for iOS and Android builds using Capacitor

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "📱 UA Homes Mobile App Setup"
echo "Repository root: $REPO_ROOT"
echo ""

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js from https://nodejs.org"
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo ""

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm is not installed. Please install npm"
    exit 1
fi

echo "✅ npm version: $(npm --version)"
echo ""

# Install Capacitor globally
echo "📦 Installing Capacitor CLI..."
npm install -g @capacitor/cli

# Install project dependencies
echo "📦 Installing project dependencies..."
cd "$REPO_ROOT"
npm install @capacitor/core @capacitor/app @capacitor/haptics @capacitor/status-bar --save-dev

echo ""
echo "🚀 Next Steps:"
echo ""
echo "For iOS (macOS only):"
echo "  1. npx cap add ios"
echo "  2. npx cap build ios"
echo "  3. open ios/App/App.xcworkspace"
echo "  4. In Xcode: Product → Archive → Distribute App"
echo ""
echo "For Android:"
echo "  1. npx cap add android"
echo "  2. npx cap build android"
echo "  3. Open android/ folder in Android Studio"
echo "  4. Build → Generate Signed Bundle / APK"
echo ""
echo "For PWA (Recommended - No Setup Needed!):"
echo "  Share this link: https://ua-homes.netlify.app/real-estate-demo.html"
echo "  Users can install directly from browser!"
echo ""
echo "📚 Read MOBILE_APP_GUIDE.md for detailed instructions"
echo ""
