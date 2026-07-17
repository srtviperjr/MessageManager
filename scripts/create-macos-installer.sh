#!/bin/bash
# Build MessageManager.app and a distributable .pkg installer.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
APP_NAME="MessageManager"
VERSION="$(python3 - <<'PY'
from pathlib import Path
import re
text = Path("app/version.py").read_text()
m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "1.0.0")
PY
)"
cd "${ROOT}"

echo "==> Building app (v${VERSION})"
"${ROOT}/scripts/create-macos-app.sh"

APP="${DIST}/${APP_NAME}.app"
PKG_ROOT="${DIST}/pkgroot"
SCRIPTS_DIR="${DIST}/pkgscripts"
COMPONENT_PKG="${DIST}/${APP_NAME}-component.pkg"
PRODUCT_PKG="${DIST}/${APP_NAME}-${VERSION}.pkg"
ID="com.srtviperjr.messagemanager"

rm -rf "${PKG_ROOT}" "${SCRIPTS_DIR}" "${COMPONENT_PKG}" "${PRODUCT_PKG}"
mkdir -p "${PKG_ROOT}/Applications" "${SCRIPTS_DIR}"

# Stage app exactly where the installer should place it.
ditto "${APP}" "${PKG_ROOT}/Applications/${APP_NAME}.app"
xattr -cr "${PKG_ROOT}/Applications/${APP_NAME}.app" 2>/dev/null || true

cp "${ROOT}/scripts/macos/pkg/postinstall" "${SCRIPTS_DIR}/postinstall"
chmod 755 "${SCRIPTS_DIR}/postinstall"

echo "==> Building component package"
pkgbuild \
  --root "${PKG_ROOT}" \
  --scripts "${SCRIPTS_DIR}" \
  --identifier "${ID}" \
  --version "${VERSION}" \
  --install-location "/" \
  "${COMPONENT_PKG}"

# Simple product package (unsigned). Users may need right-click → Open once.
echo "==> Building product package"
productbuild \
  --package "${COMPONENT_PKG}" \
  --identifier "${ID}.dist" \
  --version "${VERSION}" \
  "${PRODUCT_PKG}"

# Convenience copy without version for local use.
cp "${PRODUCT_PKG}" "${DIST}/${APP_NAME}.pkg"

# Cleanup staging
rm -rf "${PKG_ROOT}" "${SCRIPTS_DIR}" "${COMPONENT_PKG}"

cat <<EOF

Installer ready:
  ${PRODUCT_PKG}
  ${DIST}/${APP_NAME}.pkg

Install by double-clicking the .pkg (right-click → Open if Gatekeeper blocks it).
After install, grant Full Disk Access when prompted, then launch MessageManager.

To publish an update on GitHub:
  1. Commit/tag v${VERSION}
  2. gh release create v${VERSION} "${PRODUCT_PKG}" --title "MessageManager ${VERSION}" --notes "Release ${VERSION}"
EOF
