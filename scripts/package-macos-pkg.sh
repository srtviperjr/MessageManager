#!/bin/bash
# Build a macOS product .pkg with Apple's flat xar layout (Distribution +
# ComponentName.pkg/{Payload,Bom,PackageInfo,Scripts} as sibling archive members).
#
# Used when pkgbuild/productbuild are unavailable (e.g. Linux cloud agents).
# Expects a ready MessageManager.app and writes dist/MessageManager.pkg.
#
# Usage:
#   ./scripts/package-macos-pkg.sh /path/to/MessageManager.app
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="${ROOT}/dist"
APP_NAME="MessageManager"
ID="com.srtviperjr.messagemanager"
COMPONENT_NAME="${APP_NAME}-component.pkg"

APP="${1:-}"
if [[ -z "${APP}" || ! -d "${APP}" ]]; then
  echo "Usage: $0 /path/to/MessageManager.app" >&2
  exit 1
fi
APP="$(cd "$(dirname "${APP}")" && pwd)/$(basename "${APP}")"
cd "${ROOT}"

VERSION="$(
  python3 - <<'PY'
from pathlib import Path
import re
text = Path("app/version.py").read_text()
m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
print(m.group(1) if m else "0.0.0")
PY
)"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required tool not found: $1" >&2
    exit 1
  }
}
need xar
need mkbom
need cpio
need gzip

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/mm-pkg.XXXXXX")"
cleanup() { rm -rf "${STAGE}"; }
trap cleanup EXIT

PKGROOT="${STAGE}/pkgroot"
COMPDIR="${STAGE}/flat/${COMPONENT_NAME}"
SCRIPTS_SRC="${STAGE}/scripts"
mkdir -p "${PKGROOT}/Applications" "${COMPDIR}" "${SCRIPTS_SRC}" "${DIST}"

echo "==> Staging ${APP_NAME}.app (v${VERSION})"
# Prefer ditto on macOS; fall back to cp -a.
if command -v ditto >/dev/null 2>&1; then
  ditto "${APP}" "${PKGROOT}/Applications/${APP_NAME}.app"
else
  rm -rf "${PKGROOT}/Applications/${APP_NAME}.app"
  cp -a "${APP}" "${PKGROOT}/Applications/${APP_NAME}.app"
fi
find "${PKGROOT}" -name '._*' -delete

echo "==> Building Payload / Bom / Scripts"
(
  cd "${PKGROOT}"
  # odc + gzip matches Apple pkgbuild payloads we ship today.
  find . -print | cpio -o --format odc --owner 0:80 2>/dev/null | gzip -c >"${COMPDIR}/Payload"
)
mkbom "${PKGROOT}" "${COMPDIR}/Bom"

cp "${ROOT}/scripts/macos/pkg/postinstall" "${SCRIPTS_SRC}/postinstall"
chmod 755 "${SCRIPTS_SRC}/postinstall"
(
  cd "${SCRIPTS_SRC}"
  find . -print | cpio -o --format odc --owner 0:80 2>/dev/null | gzip -c >"${COMPDIR}/Scripts"
)

RAW_BYTES="$(python3 - <<PY
import gzip
from pathlib import Path
print(len(gzip.decompress(Path("${COMPDIR}/Payload").read_bytes())))
PY
)"
INSTALL_KBYTES="$(( (RAW_BYTES + 1023) / 1024 ))"
NENTRIES="$(python3 - <<PY
from pathlib import Path
root = Path("${PKGROOT}")
print(sum(1 for _ in root.rglob("*")) + 1)
PY
)"

cat >"${COMPDIR}/PackageInfo" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<pkg-info overwrite-permissions="true" relocatable="false" identifier="${ID}" postinstall-action="none" version="${VERSION}" format-version="2" install-location="/" auth="root">
    <payload numberOfFiles="${NENTRIES}" installKBytes="${INSTALL_KBYTES}"/>
    <bundle path="./Applications/${APP_NAME}.app" id="${ID}" CFBundleShortVersionString="${VERSION}" CFBundleVersion="${VERSION}"/>
    <bundle-version/>
    <upgrade-bundle>
        <bundle id="${ID}"/>
    </upgrade-bundle>
    <update-bundle/>
    <atomic-update-bundle/>
    <strict-identifier>
        <bundle id="${ID}"/>
    </strict-identifier>
    <relocate/>
    <scripts>
        <postinstall file="./postinstall" timeout="600"/>
    </scripts>
</pkg-info>
EOF

cat >"${STAGE}/flat/Distribution" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="1">
    <pkg-ref id="${ID}">
        <bundle-version>
            <bundle CFBundleShortVersionString="${VERSION}" CFBundleVersion="${VERSION}" id="${ID}" path="Applications/${APP_NAME}.app"/>
        </bundle-version>
    </pkg-ref>
    <options customize="never" require-scripts="false" hostArchitectures="x86_64,arm64"/>
    <choices-outline>
        <line choice="default">
            <line choice="${ID}"/>
        </line>
    </choices-outline>
    <choice id="default"/>
    <choice id="${ID}" visible="false">
        <pkg-ref id="${ID}"/>
    </choice>
    <pkg-ref id="${ID}" version="${VERSION}" onConclusion="none" installKBytes="${INSTALL_KBYTES}" updateKBytes="0">#${COMPONENT_NAME}</pkg-ref>
    <product id="${ID}.dist" version="${VERSION}"/>
</installer-gui-script>
EOF

PRODUCT_PKG="${DIST}/${APP_NAME}.pkg"
echo "==> Writing flat product package ${PRODUCT_PKG}"
# Critical: component must be a *directory* of members inside the product xar,
# not a nested xar file. Nested xars make Installer report
# "no software found to install".
(
  cd "${STAGE}/flat"
  # compression none on the outer archive matches Apple productbuild output.
  xar --compression none -cf "${PRODUCT_PKG}" Distribution "${COMPONENT_NAME}"
)

echo "Installer ready: ${PRODUCT_PKG}"
echo "Version: ${VERSION}"
# Sanity: require flat layout (component directory members, not nested xar).
echo "Archive TOC:"
xar -t -f "${PRODUCT_PKG}"
if ! xar -t -f "${PRODUCT_PKG}" | grep -qx "${COMPONENT_NAME}/Payload"; then
  echo "ERROR: ${PRODUCT_PKG} missing ${COMPONENT_NAME}/Payload (flat layout required)" >&2
  exit 1
fi
# Nested xar mistake: product archive contains a single file member named
# MessageManager-component.pkg with no /Payload child (xar -tf would still
# list the name alone). Presence of .../Payload above is the real check.
echo "Flat layout OK"
