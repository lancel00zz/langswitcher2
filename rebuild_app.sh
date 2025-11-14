#!/bin/bash
# LangSwitcher 2.0 - Rebuild Script

set -e  # Exit on error

# Use Python 3.13 (py2app doesn't support 3.14 yet)
PYTHON=/opt/homebrew/bin/python3.13

echo "🔧 LangSwitcher 2.0 - Rebuild Script"
echo "===================================="
echo ""
echo "Using: $PYTHON ($($PYTHON --version))"
echo ""

# Step 1: Ensure required packages are installed
echo "📦 Step 1: Installing required packages..."
$PYTHON -m pip install --user --break-system-packages setuptools py2app pyobjc-framework-WebKit || {
    echo "✅ Packages already installed or using system packages"
}
echo ""

# Step 2: Clean previous build
echo "🧹 Step 2: Cleaning previous build..."
rm -rf build dist
echo "✅ Clean complete"
echo ""

# Step 3: Build the app
echo "🔨 Step 3: Building LangSwitcher.app..."
$PYTHON setup.py py2app
echo "✅ Build complete!"
echo ""

# Step 4: Test the app
echo "🧪 Step 4: Testing the app..."
echo "Running: ./dist/LangSwitcher.app/Contents/MacOS/LangSwitcher"
echo "(Press Ctrl+C to stop)"
echo ""
./dist/LangSwitcher.app/Contents/MacOS/LangSwitcher

