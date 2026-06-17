#!/usr/bin/env bash
# Build ZH Downloader .app + .dmg + .pkg for macOS.
# Usage: ./build_mac.sh
# Requires: python3 with tkinter. Auto-installs PyInstaller.

set -e
cd "$(dirname "$0")"

APP_NAME="ZH Downloader"
APP_BUNDLE="ZH Downloader.app"
DMG_NAME="ZHDownloader-macOS.dmg"
PKG_NAME="ZHDownloader-macOS.pkg"
PY_SCRIPT="zh_downloader.py"
APP_VERSION="1.1.0"
APP_AUTHOR="ZH Motions"
APP_BUNDLE_ID="com.zhmotions.downloader"
APP_COPYRIGHT="© 2026 ZH Motions"

echo "==> 1/6 Setup virtualenv"
# Pick Python with working Tk
if [ -x "/opt/homebrew/bin/python3.12" ]; then
  PY=/opt/homebrew/bin/python3.12
elif [ -x "/opt/homebrew/bin/python3.11" ]; then
  PY=/opt/homebrew/bin/python3.11
else
  PY=python3
fi
echo "    Using $PY"

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "ERROR: $PY has no tkinter. Install: brew install python-tk@3.12"
  exit 1
fi

rm -rf .venv
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> 2/6 Install build deps"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

echo "==> 3/6 Check ffmpeg"
FFMPEG_BIN="$(command -v ffmpeg || true)"
if [ -z "$FFMPEG_BIN" ]; then
  echo "    ffmpeg not on PATH — building without it."
  ADD_BINARY=""
else
  echo "    Using $FFMPEG_BIN"
  ADD_BINARY="--add-binary $FFMPEG_BIN:."
fi

echo "==> 4/6 PyInstaller build .app"
rm -rf build dist

ICON_OPT=""
[ -f "assets/AppIcon.icns" ] && ICON_OPT="--icon=assets/AppIcon.icns"

# shellcheck disable=SC2086
pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "$APP_BUNDLE_ID" \
  $ICON_OPT \
  --add-data assets:assets \
  --hidden-import certifi --collect-data certifi \
  $ADD_BINARY \
  "$PY_SCRIPT"

# Patch Info.plist
PLIST="dist/$APP_BUNDLE/Contents/Info.plist"
if [ -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $APP_VERSION" "$PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $APP_VERSION" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $APP_VERSION" "$PLIST"
  /usr/libexec/PlistBuddy -c "Set :NSHumanReadableCopyright '$APP_COPYRIGHT'" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string '$APP_COPYRIGHT'" "$PLIST"
  /usr/libexec/PlistBuddy -c "Set :NSAppleEventsUsageDescription 'ZH Downloader uses AppleScript for notifications.'" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :NSAppleEventsUsageDescription string 'ZH Downloader uses AppleScript for notifications.'" "$PLIST"
  # Register zhdownloader:// scheme so the extension can LAUNCH the app when it's
  # closed. The scheme only opens the app; queued URLs are flushed by the
  # extension once the bridge is up (no AppleEvent / pyobjc needed).
  /usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes array" "$PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0 dict" "$PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string com.zhmotions.zhdownloader" "$PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$PLIST"
  /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string zhdownloader" "$PLIST"
  echo "    Info.plist patched (+ zhdownloader:// scheme)"
fi

[ ! -d "dist/$APP_BUNDLE" ] && echo "PyInstaller failed." && exit 1

# Ad-hoc codesign — without a signature, Apple Silicon calls the downloaded app
# "damaged" with no easy bypass. Ad-hoc turns it into the normal "unidentified
# developer" prompt that a one-time right-click → Open clears.
echo "==> Ad-hoc signing"
xattr -cr "dist/$APP_BUNDLE" 2>/dev/null || true
codesign --force --deep --sign - "dist/$APP_BUNDLE" || echo "  ⚠ codesign failed"
codesign --verify --deep --strict "dist/$APP_BUNDLE" >/dev/null 2>&1 && echo "  signed ✓" || true

echo "==> 5/6 Build .dmg"
rm -f "$DMG_NAME"

if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "$APP_NAME" \
    --window-size 540 360 \
    --icon-size 100 \
    --icon "$APP_BUNDLE" 140 180 \
    --app-drop-link 400 180 \
    --no-internet-enable \
    "$DMG_NAME" \
    "dist/$APP_BUNDLE" || {
      echo "    create-dmg failed, using hdiutil"
      USE_HDIUTIL=1
    }
else
  echo "    create-dmg not found (brew install create-dmg for nicer .dmg)"
  USE_HDIUTIL=1
fi

if [ "${USE_HDIUTIL:-0}" = "1" ]; then
  STAGE_DIR="$(mktemp -d)/dmg-stage"
  mkdir -p "$STAGE_DIR"
  cp -R "dist/$APP_BUNDLE" "$STAGE_DIR/"
  ln -s /Applications "$STAGE_DIR/Applications"
  hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_NAME"
  rm -rf "$STAGE_DIR"
fi

echo "==> 6/6 Build .pkg (installer wizard)"
rm -f "$PKG_NAME"

# ── Stage layout: /Applications/ZH Downloader.app ──
PKG_ROOT="$(mktemp -d)"
mkdir -p "$PKG_ROOT/Applications"
cp -R "dist/$APP_BUNDLE" "$PKG_ROOT/Applications/"

# ── Component package (saved as a .pkg file, not a directory) ──
COMP_DIR="$(mktemp -d)"
COMP_PKG="$COMP_DIR/component.pkg"

pkgbuild \
  --root "$PKG_ROOT" \
  --identifier "$APP_BUNDLE_ID" \
  --version "$APP_VERSION" \
  --install-location "/" \
  "$COMP_PKG"

# ── Distribution XML ──
DIST_XML="$COMP_DIR/distribution.xml"
cat > "$DIST_XML" << DISTEOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
    <title>ZH Downloader</title>
    <organization>com.zhmotions</organization>
    <domains enable_localSystem="true"/>
    <options customize="never" require-scripts="false" rootVolumeOnly="true"
             hostArchitectures="arm64,x86_64"/>
    <welcome language="en" mime-type="text/plain"><![CDATA[
ZH Downloader v${APP_VERSION}
by ${APP_AUTHOR} · zhmotions.com

Personal video downloader for ZH Motions students.
Click Continue to install to /Applications.
]]></welcome>
    <conclusion language="en" mime-type="text/plain"><![CDATA[
✓ Installed successfully.

Find ZH Downloader in your Applications folder or Launchpad.

First launch: right-click the app → Open → Open
(one-time step to bypass Gatekeeper for unsigned apps)
]]></conclusion>
    <choices-outline>
        <line choice="default">
            <line choice="${APP_BUNDLE_ID}"/>
        </line>
    </choices-outline>
    <choice id="default"/>
    <choice id="${APP_BUNDLE_ID}" visible="false">
        <pkg-ref id="${APP_BUNDLE_ID}"/>
    </choice>
    <pkg-ref id="${APP_BUNDLE_ID}" version="${APP_VERSION}" onConclusion="none">component.pkg</pkg-ref>
</installer-gui-script>
DISTEOF

productbuild \
  --distribution "$DIST_XML" \
  --package-path "$COMP_DIR" \
  --version "$APP_VERSION" \
  "$PKG_NAME"

# Cleanup temp files
rm -rf "$PKG_ROOT" "$COMP_DIR"

echo ""
echo "✓ Done!"
echo ""
echo "  • $(pwd)/$DMG_NAME   — drag-to-Applications installer"
echo "  • $(pwd)/$PKG_NAME   — double-click installer wizard (recommended)"
echo "  • $(pwd)/dist/$APP_BUNDLE  — raw .app"
echo ""
echo "Send the .pkg to students:"
echo "  Double-click → Continue → Install → Enter password → Done"
echo ""
echo "First launch after install:"
echo "  Right-click app → Open → Open  (Gatekeeper bypass, one-time only)"
