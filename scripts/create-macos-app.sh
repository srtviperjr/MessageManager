#!/bin/bash
# Build a double-clickable macOS app: dist/MessageManager.app
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
APP_NAME="MessageManager"
APP="${DIST}/${APP_NAME}.app"
CONTENTS="${APP}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
APP_PAYLOAD="${RESOURCES}/app"

echo "Building ${APP}"
rm -rf "${APP}"
mkdir -p "${MACOS}" "${APP_PAYLOAD}"

# Bundle project files (not venv, data, git, dist)
rsync -a \
  --exclude '.git' \
  --exclude '.cursor' \
  --exclude 'dist' \
  --exclude 'data' \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "${ROOT}/" "${APP_PAYLOAD}/"

cp "${ROOT}/scripts/macos/launch.sh" "${MACOS}/${APP_NAME}"
chmod +x "${MACOS}/${APP_NAME}"

if [[ -f "${ROOT}/assets/AppIcon.icns" ]]; then
  cp "${ROOT}/assets/AppIcon.icns" "${RESOURCES}/AppIcon.icns"
fi

cat > "${CONTENTS}/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleDisplayName</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIdentifier</key>
  <string>com.local.messagemanager</string>
  <key>CFBundleVersion</key>
  <string>0.1.0</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>${APP_NAME}</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

# Clear quarantine so the other Mac can open it after AirDrop/USB (still may need right-click Open once)
xattr -cr "${APP}" 2>/dev/null || true

echo "Done: ${APP}"
echo
echo "Copy \"${APP_NAME}.app\" to the other Mac's Applications folder."
echo "On first launch: right-click → Open (if Gatekeeper blocks it),"
echo "then grant Full Disk Access to MessageManager."
