#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Data Handler"
BUNDLE_ID="com.dit.data-handler"
MIN_SYSTEM_VERSION="13.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build/macos"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_ROOT="$APP_RESOURCES/app"
APP_BINARY="$APP_MACOS/$APP_NAME"
VENV_DIR="$APP_RESOURCES/venv"
ICON_SOURCE="$ROOT_DIR/packaging/assets/DataHandlerIcon.icns"
ICON_DEST="$APP_RESOURCES/DataHandlerIcon.icns"
DMG_PATH="$DIST_DIR/$APP_NAME.dmg"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "python3 is required to package $APP_NAME" >&2
  exit 1
fi

if [[ ! -f "$ICON_SOURCE" ]]; then
  echo "Missing icon: $ICON_SOURCE" >&2
  exit 1
fi

rm -rf "$BUILD_DIR" "$APP_BUNDLE" "$DMG_PATH"
mkdir -p "$BUILD_DIR" "$APP_MACOS" "$APP_RESOURCES" "$APP_ROOT"

swiftc \
  "$ROOT_DIR/packaging/macos/DataHandlerApp.swift" \
  -framework Cocoa \
  -framework WebKit \
  -o "$APP_BINARY"
chmod +x "$APP_BINARY"

cp "$ICON_SOURCE" "$ICON_DEST"

cat >"$APP_CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>en</string>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIconFile</key>
  <string>DataHandlerIcon</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

rsync -a \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '.ruff_cache' \
  --exclude '.mypy_cache' \
  --exclude '__pycache__' \
  --exclude '.venv' \
  --exclude 'build' \
  --exclude 'dist' \
  --exclude '.pipeline' \
  --exclude 'artifacts' \
  "$ROOT_DIR/orchestrator" \
  "$ROOT_DIR/DataManager" \
  "$ROOT_DIR/DataHelper" \
  "$APP_ROOT/"

"$PYTHON_BIN" -m venv --copies "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools
"$VENV_DIR/bin/python" -m pip install \
  "$APP_ROOT/DataManager" \
  "$APP_ROOT/DataHelper" \
  "fastapi>=0.115" \
  "uvicorn[standard]>=0.30"

/usr/bin/codesign --force --deep --sign - "$APP_BUNDLE"

/usr/bin/hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$APP_BUNDLE" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "$APP_BUNDLE"
echo "$DMG_PATH"
