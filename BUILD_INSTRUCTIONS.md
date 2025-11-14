# LangSwitcher 2.0 - Build Instructions

## ⚠️ Requirements

- **Python 3.13** (py2app doesn't support Python 3.14 yet)
- If you have Python 3.14, install 3.13: `brew install python@3.13`

## 📦 Building the macOS Application

### Step 1: Prepare Your Icon

You need to convert your icon image to `.icns` format:

#### Option A: Using Online Tool
1. Save your icon image as PNG (1024x1024 recommended)
2. Go to https://cloudconvert.com/png-to-icns
3. Upload and convert
4. Save as `icon.icns` in the project root

#### Option B: Using macOS Terminal
```bash
# Create iconset folder
mkdir icon.iconset

# Resize your PNG to required sizes (if you have ImageMagick)
sips -z 16 16     icon-1024.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon-1024.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon-1024.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon-1024.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon-1024.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon-1024.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon-1024.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon-1024.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon-1024.png --out icon.iconset/icon_512x512.png
sips -z 1024 1024 icon-1024.png --out icon.iconset/icon_512x512@2x.png

# Convert to icns
iconutil -c icns icon.iconset
```

**Important:** The file must be named `icon.icns` and placed in the project root.

---

### Step 2: Clean Previous Builds

```bash
cd /Users/patrick.zakher/Documents/git-repo/my_projects/langswitcher2
rm -rf build dist
```

---

### Step 3: Build the Application

```bash
python3 setup.py py2app
```

This will:
- Bundle Python runtime
- Include all dependencies
- Add your icon
- Set version to 2.0
- Create `dist/LangSwitcher.app`

---

### Step 4: Test the Application

```bash
# Run from terminal to see logs
./dist/LangSwitcher.app/Contents/MacOS/LangSwitcher
```

Or just double-click `dist/LangSwitcher.app` in Finder.

---

### Step 5: Verify Version Info

1. In Finder, navigate to `dist/`
2. Right-click `LangSwitcher.app`
3. Click "Get Info" (⌘+I)
4. You should see:
   - **Version:** 2.0
   - **Copyright:** © 2025 Lanceloz Inc.
   - Your custom icon

---

### Step 6: Install to Applications

```bash
# Copy to Applications folder
cp -R dist/LangSwitcher.app /Applications/

# Or drag from Finder
```

---

## 🔧 Troubleshooting

### "Cannot find icon.icns"
- Make sure `icon.icns` is in the project root
- Check filename is exactly `icon.icns` (case-sensitive)

### App won't start
- Check permissions: `xattr -cr /Applications/LangSwitcher.app`
- Run from terminal to see error messages

### Version not showing
- Verify `version.py` has `__version__ = "2.0"`
- Rebuild: `rm -rf build dist && python3 setup.py py2app`

---

## 📝 Notes

- The app will **NOT** show in the Dock (it's a menu bar app)
- Icon appears in:
  - `/Applications` folder
  - Finder "Get Info"
  - App Switcher (⌘+Tab)
  - Activity Monitor
- Menu bar shows flag icons (🇺🇸/🇫🇷) not the app icon

---

## 🚀 Distribution

To share with others:
1. Compress: `cd dist && zip -r LangSwitcher-2.0.zip LangSwitcher.app`
2. Share the `.zip` file
3. Users extract and drag to `/Applications`

For code signing (optional, for wider distribution):
```bash
codesign --force --deep --sign - dist/LangSwitcher.app
```

