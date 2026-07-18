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
print(m.group(1) if m else "0.0.0")
PY
)"
cd "${ROOT}"

echo "==> Building app (v${VERSION})"
"${ROOT}/scripts/create-macos-app.sh"

# Prefer the staged build path written by create-macos-app.sh.
if [[ -f "${DIST}/.last-app-path" ]]; then
  APP="$(cat "${DIST}/.last-app-path")"
fi
if [[ -z "${APP:-}" || ! -d "${APP}" ]]; then
  APP="${DIST}/.build/${APP_NAME}.app"
fi
if [[ ! -d "${APP}" && -d "${DIST}/${APP_NAME}.app" ]]; then
  APP="${DIST}/${APP_NAME}.app"
fi
if [[ ! -d "${APP}" ]]; then
  echo "ERROR: built app not found" >&2
  exit 1
fi
PKG_ROOT="${DIST}/pkgroot"
SCRIPTS_DIR="${DIST}/pkgscripts"
COMPONENT_PKG="${DIST}/${APP_NAME}-component.pkg"
PRODUCT_PKG="${DIST}/${APP_NAME}-${VERSION}.pkg"
COMPONENT_PLIST="${ROOT}/scripts/macos/pkg/component.plist"
ID="com.srtviperjr.messagemanager"

rm -rf "${PKG_ROOT}" "${SCRIPTS_DIR}" "${COMPONENT_PKG}" "${PRODUCT_PKG}"
mkdir -p "${PKG_ROOT}/Applications" "${SCRIPTS_DIR}"

# Stage app exactly where the installer should place it.
ditto "${APP}" "${PKG_ROOT}/Applications/${APP_NAME}.app"
xattr -cr "${PKG_ROOT}/Applications/${APP_NAME}.app" 2>/dev/null || true
# Ensure executable bit survives packaging.
chmod +x "${PKG_ROOT}/Applications/${APP_NAME}.app/Contents/MacOS/${APP_NAME}"

cp "${ROOT}/scripts/macos/pkg/postinstall" "${SCRIPTS_DIR}/postinstall"
chmod 755 "${SCRIPTS_DIR}/postinstall"

# BundleIsRelocatable=false is critical: otherwise Installer may "upgrade" an
# existing copy under ~/Documents/.../dist instead of installing to /Applications.
echo "==> Building component package (forced /Applications install)"
pkgbuild \
  --root "${PKG_ROOT}" \
  --component-plist "${COMPONENT_PLIST}" \
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
The installer places MessageManager.app in /Applications (not relocatable) and
installs Python 3.12+ plus pip dependencies when missing.

To publish an update on GitHub:
  1. Commit/tag v${VERSION}
  2. gh release create v${VERSION} "${PRODUCT_PKG}" --title "MessageManager ${VERSION}" --notes "Release ${VERSION}"
EOF
