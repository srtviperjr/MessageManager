#!/bin/bash
# Build MessageManager.app and a distributable MessageManager.pkg installer.
#
# Optional signing / notarization (removes Gatekeeper "untrusted developer" steps):
#   export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#   export INSTALLER_IDENTITY="Developer ID Installer: Your Name (TEAMID)"
#   export NOTARY_PROFILE="notary-profile"   # from: xcrun notarytool store-credentials
# Then re-run this script. Requires an Apple Developer Program membership.
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
UNSIGNED_PKG="${DIST}/${APP_NAME}-unsigned.pkg"
PRODUCT_PKG="${DIST}/${APP_NAME}.pkg"
COMPONENT_PLIST="${ROOT}/scripts/macos/pkg/component.plist"
ID="com.srtviperjr.messagemanager"

# Remove any older versioned pkgs so releases stay unversioned.
rm -rf "${PKG_ROOT}" "${SCRIPTS_DIR}" "${COMPONENT_PKG}" "${UNSIGNED_PKG}" "${PRODUCT_PKG}"
rm -f "${DIST}/${APP_NAME}"-*.pkg 2>/dev/null || true
mkdir -p "${PKG_ROOT}/Applications" "${SCRIPTS_DIR}"

# Stage app exactly where the installer should place it.
ditto "${APP}" "${PKG_ROOT}/Applications/${APP_NAME}.app"
xattr -cr "${PKG_ROOT}/Applications/${APP_NAME}.app" 2>/dev/null || true
chmod +x "${PKG_ROOT}/Applications/${APP_NAME}.app/Contents/MacOS/${APP_NAME}"

if [[ -n "${CODESIGN_IDENTITY:-}" ]]; then
  echo "==> Codesigning app with ${CODESIGN_IDENTITY}"
  codesign --force --deep --options runtime --timestamp \
    --sign "${CODESIGN_IDENTITY}" \
    "${PKG_ROOT}/Applications/${APP_NAME}.app"
  codesign --verify --deep --strict --verbose=2 \
    "${PKG_ROOT}/Applications/${APP_NAME}.app"
else
  echo "==> Skipping app codesign (set CODESIGN_IDENTITY to enable)"
fi

cp "${ROOT}/scripts/macos/pkg/postinstall" "${SCRIPTS_DIR}/postinstall"
chmod 755 "${SCRIPTS_DIR}/postinstall"

# BundleIsRelocatable=false is critical: otherwise Installer may "upgrade" an
# existing copy under ~/Documents/.../dist instead of installing to /Applications.
echo "==> Building component package (forced /Applications install)"
PKGBUILD_ARGS=(
  --root "${PKG_ROOT}"
  --component-plist "${COMPONENT_PLIST}"
  --scripts "${SCRIPTS_DIR}"
  --identifier "${ID}"
  --version "${VERSION}"
  --install-location "/"
)
if [[ -n "${INSTALLER_IDENTITY:-}" ]]; then
  PKGBUILD_ARGS+=(--sign "${INSTALLER_IDENTITY}")
fi
pkgbuild "${PKGBUILD_ARGS[@]}" "${COMPONENT_PKG}"

echo "==> Building product package"
productbuild \
  --package "${COMPONENT_PKG}" \
  --identifier "${ID}.dist" \
  --version "${VERSION}" \
  "${UNSIGNED_PKG}"

if [[ -n "${INSTALLER_IDENTITY:-}" ]]; then
  echo "==> Signing installer with ${INSTALLER_IDENTITY}"
  productsign --sign "${INSTALLER_IDENTITY}" "${UNSIGNED_PKG}" "${PRODUCT_PKG}"
  rm -f "${UNSIGNED_PKG}"
else
  mv "${UNSIGNED_PKG}" "${PRODUCT_PKG}"
  echo "==> Skipping installer sign (set INSTALLER_IDENTITY to enable)"
fi

if [[ -n "${NOTARY_PROFILE:-}" ]]; then
  echo "==> Submitting ${PRODUCT_PKG} for notarization"
  xcrun notarytool submit "${PRODUCT_PKG}" \
    --keychain-profile "${NOTARY_PROFILE}" \
    --wait
  echo "==> Stapling notarization ticket"
  xcrun stapler staple "${PRODUCT_PKG}"
  spctl --assess --type install -vv "${PRODUCT_PKG}" || true
else
  echo "==> Skipping notarization (set NOTARY_PROFILE to enable)"
fi

# Cleanup staging
rm -rf "${PKG_ROOT}" "${SCRIPTS_DIR}" "${COMPONENT_PKG}"

cat <<EOF

Installer ready:
  ${PRODUCT_PKG}

Install by double-clicking MessageManager.pkg.
After install, grant Full Disk Access when prompted, then launch MessageManager.

Gatekeeper / "trust" prompts:
  Unsigned builds (current default) always need right-click → Open the first time
  after a browser download. To install with a normal double-click on any Mac:
    1. Join Apple Developer Program
    2. Create Developer ID Application + Developer ID Installer certificates
    3. export CODESIGN_IDENTITY=... INSTALLER_IDENTITY=... NOTARY_PROFILE=...
    4. Re-run this script (signs + notarizes)

To publish an update on GitHub:
  1. Commit/tag v${VERSION}
  2. gh release create v${VERSION} "${PRODUCT_PKG}" --title "MessageManager ${VERSION}" --notes "Release ${VERSION}"
EOF
