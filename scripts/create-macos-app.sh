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
rm -rf "${APP}"
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

cp "${ROOT}/scripts/macos/launch.sh" "${MACOS}/${APP_NAME}"
chmod +x "${MACOS}/${APP_NAME}"

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

echo "Done: ${APP}"
echo "Version: ${VERSION}"
