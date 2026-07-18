#!/bin/bash
# Build a double-clickable macOS app: dist/MessageManager.app
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
APP_NAME="MessageManager"
# Stage under .build so rebuilds work even if a prior root-owned
# dist/MessageManager.app was left behind by an installer dry-run.
BUILD_ROOT="${DIST}/.build"
APP="${BUILD_ROOT}/${APP_NAME}.app"
FINAL_APP="${DIST}/${APP_NAME}.app"
CONTENTS="${APP}/Contents"
MACOS="${CONTENTS}/MacOS"
RESOURCES="${CONTENTS}/Resources"
APP_PAYLOAD="${RESOURCES}/app"

VERSION="$(
  python3 - <<'PY'
from pathlib import Path
import re
text = Path("app/version.py").read_text()
m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "1.0.0")
PY
)"
BUNDLE_ID="$(
  python3 - <<'PY'
from pathlib import Path
import re
text = Path("app/version.py").read_text()
m = re.search(r'BUNDLE_ID\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "com.srtviperjr.messagemanager")
PY
)"

cd "${ROOT}"
echo "Building ${APP} (v${VERSION})"
rm -rf "${BUILD_ROOT}"
mkdir -p "${MACOS}" "${APP_PAYLOAD}"

# Bundle project files (not venv, data, git, dist, tools)
rsync -a \
  --exclude '.git' \
  --exclude '.cursor' \
  --exclude 'dist' \
  --exclude 'data' \
  --exclude '.tools' \
  --exclude '.venv' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'logs' \
  "${ROOT}/" "${APP_PAYLOAD}/"

# Native AppKit executable so Full Disk Access applies AND the Dock bounce stops.
# (execl→bash made macOS think the app never finished launching.)
clang -Os -arch arm64 -arch x86_64 \
  -framework AppKit -framework Foundation \
  -o "${MACOS}/${APP_NAME}" "${ROOT}/scripts/macos/launcher.m"
chmod +x "${MACOS}/${APP_NAME}"
chmod +x "${APP_PAYLOAD}/scripts/macos/launch.sh"
chmod +x "${APP_PAYLOAD}/scripts/macos/grant-full-disk-access.sh" \
  "${APP_PAYLOAD}/scripts/macos/grant-full-disk-access.command" \
  "${APP_PAYLOAD}/scripts/macos/sync-messages-cache.command" \
  "${APP_PAYLOAD}/scripts/macos/sync-messages-cache.py" 2>/dev/null || true

if [[ -f "${ROOT}/assets/AppIcon.icns" ]]; then
  cp "${ROOT}/assets/AppIcon.icns" "${RESOURCES}/AppIcon.icns"
fi

# Embed version for the launcher / updates UI.
printf '%s\n' "${VERSION}" > "${RESOURCES}/VERSION"

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
  <string>${BUNDLE_ID}</string>
  <key>CFBundleVersion</key>
  <string>${VERSION}</string>
  <key>CFBundleShortVersionString</key>
  <string>${VERSION}</string>
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
  <key>NSAppleEventsUsageDescription</key>
  <string>MessageManager shows setup prompts and can open System Settings for Full Disk Access.</string>
</dict>
</plist>
EOF

# Clear quarantine so the other Mac can open it after AirDrop/USB (still may need right-click Open once)
xattr -cr "${APP}" 2>/dev/null || true

# Best-effort publish to dist/MessageManager.app for local use.
if rm -rf "${FINAL_APP}" 2>/dev/null; then
  ditto "${APP}" "${FINAL_APP}"
  xattr -cr "${FINAL_APP}" 2>/dev/null || true
  echo "Done: ${FINAL_APP}"
else
  echo "Done: ${APP}"
  echo "Note: could not replace ${FINAL_APP} (permission denied). Using staged build above."
fi
echo "Version: ${VERSION}"
# Always expose the usable app path for the installer script.
printf '%s\n' "${APP}" > "${DIST}/.last-app-path"
