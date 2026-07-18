#!/bin/bash
# Open Full Disk Access settings and reveal the apps macOS needs you to enable.
# Full Disk Access cannot be granted silently by a script — you still toggle the
# switches in System Settings, then fully quit and reopen MessageManager.

set -euo pipefail

APP="${MESSAGEMANAGER_APP:-/Applications/MessageManager.app}"
BUNDLE_ID="${MESSAGEMANAGER_BUNDLE_ID:-com.srtviperjr.messagemanager}"
FDA_URL="x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles"

echo ""
echo "MessageManager — Full Disk Access helper"
echo "========================================"
echo ""
echo "macOS does not allow apps to turn on Full Disk Access automatically."
echo "This script opens the right settings pane and shows which apps to enable."
echo ""

if [[ ! -d "${APP}" ]]; then
  echo "WARNING: ${APP} not found."
  echo "Install MessageManager to /Applications first, then run this again."
  echo ""
else
  echo "1) Enabling targets to add:"
  echo "   - ${APP}"
fi

# Optional Python / FDA target passed by the app (or discovered).
FDA_TARGET="${MESSAGEMANAGER_FDA_TARGET:-}"
if [[ -z "${FDA_TARGET}" ]]; then
  for version in 3.13 3.12 3.11 3.10 3.9; do
    candidate="/Library/Frameworks/Python.framework/Versions/${version}/Resources/Python.app"
    if [[ -d "${candidate}" ]]; then
      FDA_TARGET="${candidate}"
      break
    fi
  done
fi
if [[ -n "${FDA_TARGET}" && -e "${FDA_TARGET}" ]]; then
  echo "   - ${FDA_TARGET}"
fi

echo ""
echo "2) Opening System Settings → Privacy & Security → Full Disk Access…"
open "${FDA_URL}" 2>/dev/null || open "/System/Library/PreferencePanes/Security.prefPane" || true
sleep 0.6

if [[ -d "${APP}" ]]; then
  echo "3) Revealing MessageManager.app in Finder (drag it into the list if needed)…"
  open -R "${APP}" || true
fi
if [[ -n "${FDA_TARGET}" && -e "${FDA_TARGET}" ]]; then
  echo "4) Revealing Python target in Finder…"
  open -R "${FDA_TARGET}" || true
fi

echo ""
echo "In Full Disk Access:"
echo "  • Turn ON MessageManager"
if [[ -n "${FDA_TARGET}" ]]; then
  echo "  • Turn ON $(basename "${FDA_TARGET}") (or the Python entry shown in Finder)"
fi
echo "  • If already checked, toggle OFF then ON"
echo "  • Fully quit MessageManager (Quit in the app window), then reopen it"
echo ""

if [[ "${1:-}" == "--reset" ]]; then
  echo "Resetting privacy decisions for ${BUNDLE_ID} (you will need to re-enable FDA)…"
  tccutil reset All "${BUNDLE_ID}" 2>/dev/null || \
    echo "Could not reset TCC (normal without admin / on some macOS versions)."
  echo ""
fi

echo "Done. Return to MessageManager and press Recheck."
echo ""

# Keep Terminal open when launched as a .command double-click.
if [[ "${0}" == *.command || "${KEEP_TERMINAL_OPEN:-}" == "1" ]]; then
  read -r -p "Press Return to close…" _
fi
