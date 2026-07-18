#!/bin/bash
# Open Full Disk Access settings and reveal the apps macOS needs you to enable.
# Full Disk Access cannot be granted silently by a script — you still toggle the
# switches in System Settings. Prefer Python.app + MessageManager.app (not Terminal).

set -euo pipefail

APP="${MESSAGEMANAGER_APP:-/Applications/MessageManager.app}"
BUNDLE_ID="${MESSAGEMANAGER_BUNDLE_ID:-com.srtviperjr.messagemanager}"
FDA_URL="x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles"

echo ""
echo "MessageManager — Full Disk Access helper"
echo "========================================"
echo ""
echo "macOS does not allow apps to turn on Full Disk Access automatically."
echo "Enable MessageManager.app and Python.app (python.org). Terminal is only a workaround."
echo ""

if [[ ! -d "${APP}" ]]; then
  echo "WARNING: ${APP} not found."
  echo "Install MessageManager to /Applications first, then run this again."
  echo ""
else
  echo "1) Targets to enable:"
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

# Register apps with TCC so they appear in the Full Disk Access list.
echo ""
echo "2) Registering apps with macOS (so they show up in the FDA list)…"
PROBE_DIR="${HOME}/Library/Application Support/MessageManager/logs"
mkdir -p "${PROBE_DIR}"
if [[ -x "${APP}/Contents/MacOS/MessageManager" ]]; then
  "${APP}/Contents/MacOS/MessageManager" --probe-fda "${PROBE_DIR}/fda-register-app.json" \
    >/dev/null 2>&1 || true
  echo "   - probed MessageManager.app"
fi
PYTHON_BIN=""
if [[ -n "${FDA_TARGET}" && -x "${FDA_TARGET}/Contents/MacOS/Python" ]]; then
  PYTHON_BIN="${FDA_TARGET}/Contents/MacOS/Python"
elif [[ -n "${FDA_TARGET}" && -x "${FDA_TARGET}/Contents/MacOS/python3" ]]; then
  PYTHON_BIN="${FDA_TARGET}/Contents/MacOS/python3"
fi
if [[ -n "${PYTHON_BIN}" ]]; then
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1 || true
from pathlib import Path
p = Path.home() / "Library" / "Messages" / "chat.db"
try:
    with p.open("rb") as handle:
        handle.read(1)
except Exception:
    pass
PY
  echo "   - probed Python.app"
fi

echo ""
echo "3) Opening System Settings → Privacy & Security → Full Disk Access…"
open "${FDA_URL}" 2>/dev/null || open "/System/Library/PreferencePanes/Security.prefPane" || true
sleep 0.6

if [[ -d "${APP}" ]]; then
  echo "4) Revealing MessageManager.app in Finder (use + to add it if missing)…"
  open -R "${APP}" || true
fi
if [[ -n "${FDA_TARGET}" && -e "${FDA_TARGET}" ]]; then
  echo "5) Revealing Python.app in Finder…"
  open -R "${FDA_TARGET}" || true
fi

echo ""
echo "In Full Disk Access:"
echo "  • Turn ON MessageManager"
if [[ -n "${FDA_TARGET}" ]]; then
  echo "  • Turn ON Python / $(basename "${FDA_TARGET}") — the python.org app, not Terminal"
fi
echo "  • If already checked, toggle OFF then ON"
echo "  • Return to MessageManager → Retest → Sync cache (Python.app)"
echo "  • Then fully Quit MessageManager and reopen (so launch cache copy can use FDA)"
echo ""

if [[ "${1:-}" == "--reset" ]]; then
  echo "Resetting privacy decisions for ${BUNDLE_ID} (you will need to re-enable FDA)…"
  tccutil reset All "${BUNDLE_ID}" 2>/dev/null || \
    echo "Could not reset TCC (normal without admin / on some macOS versions)."
  echo ""
fi

echo "Done."
echo ""

# Keep Terminal open when launched as a .command double-click.
if [[ "${0}" == *.command || "${KEEP_TERMINAL_OPEN:-}" == "1" ]]; then
  read -r -p "Press Return to close…" _
fi
