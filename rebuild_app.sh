#!/bin/bash
# Build a local macOS bundle without changing global Python packages.

set -euo pipefail

LANGSWITCHER_SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$LANGSWITCHER_SCRIPT_DIR"

LANGSWITCHER_BUILD_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --build-only) LANGSWITCHER_BUILD_ONLY=true ;;
        -h|--help)
            echo "Usage: bash rebuild_app.sh [--build-only]"
            echo "By default, build and launch the app for interactive testing."
            echo "--build-only builds the bundle without starting a keyboard listener."
            exit 0
            ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# Keep the interpreter and build tools consistent with this app's packaging.
LANGSWITCHER_BASE_PYTHON=/opt/homebrew/bin/python3.13
LANGSWITCHER_BUILD_PYTHON="$LANGSWITCHER_SCRIPT_DIR/.build-venv/bin/python"
if [ ! -x "$LANGSWITCHER_BASE_PYTHON" ]; then
    echo "Python 3.13 is required: brew install python@3.13" >&2
    exit 1
fi

echo "🔧 LangSwitcher - Rebuild Script"
echo "===================================="
echo ""
echo "Using: $LANGSWITCHER_BASE_PYTHON ($($LANGSWITCHER_BASE_PYTHON --version))"
echo ""

# Step 1: Use an isolated environment for runtime dependencies and build tools.
echo "📦 Step 1: Installing required packages..."
if [ ! -x "$LANGSWITCHER_BUILD_PYTHON" ]; then
    "$LANGSWITCHER_BASE_PYTHON" -m venv .build-venv
fi
"$LANGSWITCHER_BUILD_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir \
    -r requirements.txt \
    'setuptools==80.3.1' 'py2app==0.28.10' 'modulegraph==0.19.7'
echo ""

# Step 2: Set build timestamp
echo "⏰ Step 2: Setting build timestamp..."
LANGSWITCHER_BUILD_TIME=$(date "+%Y%m%d.%H%M")
sed -i '' "s/__build__ = \"[0-9]*\.[0-9]*\"/__build__ = \"$LANGSWITCHER_BUILD_TIME\"/" version.py
echo "✅ Build timestamp: $LANGSWITCHER_BUILD_TIME"
echo ""

# Step 3: Clean previous build
echo "🧹 Step 3: Cleaning previous build..."
rm -rf build dist
echo "✅ Clean complete"
echo ""

# Step 4: Build the app
echo "🔨 Step 4: Building LangSwitcher.app..."
"$LANGSWITCHER_BUILD_PYTHON" setup.py py2app
echo "✅ Build complete!"
echo ""

# Step 5: Optionally launch for interactive testing.
if [ "$LANGSWITCHER_BUILD_ONLY" = true ]; then
    echo "Built: $LANGSWITCHER_SCRIPT_DIR/dist/LangSwitcher.app"
    exit 0
fi

echo "🧪 Step 5: Testing the app..."
echo "Quit the installed LangSwitcher first so only one copy handles keystrokes."
echo "Running: ./dist/LangSwitcher.app/Contents/MacOS/LangSwitcher"
echo "(Press Ctrl+C to stop)"
echo ""
exec ./dist/LangSwitcher.app/Contents/MacOS/LangSwitcher

