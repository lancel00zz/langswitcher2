#!/bin/bash
echo "=== LangSwitcher Debug Script ==="
echo "Run this on your M1 MacBook after copying the app"
echo ""

APP_PATH="$1"
if [ -z "$APP_PATH" ]; then
    echo "Usage: $0 /path/to/LangSwitcher.app"
    exit 1
fi

echo "1. Checking app existence..."
if [ ! -d "$APP_PATH" ]; then
    echo "❌ App not found at: $APP_PATH"
    exit 1
fi
echo "✅ App exists"

echo ""
echo "2. Checking extended attributes..."
xattr -l "$APP_PATH"

echo ""
echo "3. Checking permissions..."
ls -la "$APP_PATH"

echo ""
echo "4. Checking binary..."
file "$APP_PATH/Contents/MacOS/LangSwitcher"

echo ""
echo "5. Checking dependencies..."
otool -L "$APP_PATH/Contents/MacOS/LangSwitcher"

echo ""
echo "6. Testing Gatekeeper..."
spctl -a -t exec -vv "$APP_PATH"

echo ""
echo "7. Attempting launch..."
"$APP_PATH/Contents/MacOS/LangSwitcher" &
sleep 2
kill $! 2>/dev/null

echo ""
echo "=== Fixes to try ==="
echo "sudo xattr -cr '$APP_PATH'"
echo "sudo chmod -R 755 '$APP_PATH'"
echo "sudo chown -R \$(whoami):staff '$APP_PATH'"
