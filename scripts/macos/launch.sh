#!/bin/bash
set -euo pipefail

APP_SUPPORT="${HOME}/Library/Application Support/MessageManager"
LOG_DIR="${APP_SUPPORT}/logs"
MESSAGES_CACHE="${APP_SUPPORT}/messages-cache"
mkdir -p "${LOG_DIR}" "${APP_SUPPORT}/data" "${MESSAGES_CACHE}"
LOG_FILE="${LOG_DIR}/launch.log"
SERVER_LOG="${LOG_DIR}/server.log"
export THREAD_LEDGER_DATA="${APP_SUPPORT}/data"
CONTACTS_CACHE="${APP_SUPPORT}/contacts-cache"
mkdir -p "${CONTACTS_CACHE}"
# Native launcher sets these after copying DBs under Full Disk Access.
if [[ -z "${THREAD_LEDGER_MESSAGES_CACHE:-}" && -f "${MESSAGES_CACHE}/chat.db" ]]; then
  export THREAD_LEDGER_MESSAGES_CACHE="${MESSAGES_CACHE}"
fi
if [[ -z "${THREAD_LEDGER_CONTACTS_CACHE:-}" ]] && {
  [[ -f "${CONTACTS_CACHE}/AddressBook-v22.abcddb" ]] || [[ -d "${CONTACTS_CACHE}/Sources" ]]
}; then
  export THREAD_LEDGER_CONTACTS_CACHE="${CONTACTS_CACHE}"
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}" >/dev/null
}

die() {
  local msg="$1"
  log "ERROR: ${msg}"
  local escaped
  escaped="$(printf '%s' "${msg}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  # Non-blocking: a modal dialog here made Dock launches look like "nothing happened".
  osascript -e "display notification \"${escaped}\" with title \"MessageManager\" subtitle \"Launch failed\"" >/dev/null 2>&1 || true
  exit 1
}

# Resolve bundled app root: .../MessageManager.app/Contents/Resources/app
# Native launcher runs this file from Resources/app/scripts/macos/launch.sh.
# Legacy layout ran it from Contents/MacOS/MessageManager.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "${SCRIPT_DIR}/../../run.py" ]]; then
  ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
elif [[ -d "${SCRIPT_DIR}/../Resources/app" ]]; then
  ROOT="$(cd "${SCRIPT_DIR}/../Resources/app" && pwd)"
else
  die "Cannot locate MessageManager app resources from ${SCRIPT_DIR}"
fi
VENV="${APP_SUPPORT}/venv"
PORT=8741
URL="http://127.0.0.1:${PORT}"
PID_FILE="${APP_SUPPORT}/server.pid"
PYTHON_BIN=""

cd "${ROOT}"
log "Launching from ${ROOT}"
log "Logs: ${LOG_FILE} and ${SERVER_LOG} (also app.log in the same folder)"

python_usable() {
  local candidate="$1"
  [[ -x "${candidate}" ]] || return 1
  if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

is_preferred_python() {
  local candidate="$1"
  [[ "${candidate}" == /Library/Frameworks/Python.framework/* ]] \
    || [[ "${candidate}" == /opt/homebrew/bin/python3 ]] \
    || [[ "${candidate}" == /usr/local/bin/python3 ]]
}

find_python() {
  # Prefer python.org / Homebrew. Avoid /usr/bin/python3 (CLT) when possible —
  # Full Disk Access on Message.app does not transfer to that interpreter.
  local preferred=(
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.9/bin/python3"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
  )
  local fallback=(
    "$(command -v python3 2>/dev/null || true)"
    "/usr/bin/python3"
  )
  local c
  for c in "${preferred[@]}" "${fallback[@]}"; do
    [[ -n "${c}" ]] || continue
    if python_usable "${c}"; then
      echo "${c}"
      return 0
    fi
  done
  return 1
}

venv_base_python() {
  local cfg="${VENV}/pyvenv.cfg"
  [[ -f "${cfg}" ]] || return 1
  local home
  home="$(awk -F' = ' '/^home/ {print $2; exit}' "${cfg}" 2>/dev/null || true)"
  [[ -n "${home}" ]] || return 1
  if [[ -x "${home}/python3" ]]; then
    echo "${home}/python3"
  elif [[ -x "${home}/python" ]]; then
    echo "${home}/python"
  else
    echo "${home}"
  fi
}

setup_runtime() {
  local system_python
  if ! system_python="$(find_python)"; then
    die "Python 3.9+ is not installed (or only the macOS stub is present).

Install Python from https://www.python.org/downloads/macos/
then open MessageManager again."
  fi
  log "Using Python: ${system_python} ($("${system_python}" -V 2>&1))"
  if ! is_preferred_python "${system_python}"; then
    log "WARN: using system/CLT Python — grant Full Disk Access to Python as well as MessageManager"
  fi

  local rebuild_venv=0
  if [[ -x "${VENV}/bin/python" ]] && python_usable "${VENV}/bin/python"; then
    local base
    base="$(venv_base_python || true)"
    if is_preferred_python "${system_python}" && [[ -n "${base}" ]] && ! is_preferred_python "${base}"; then
      log "Existing venv is based on ${base}; recreating with ${system_python}"
      rebuild_venv=1
    else
      PYTHON_BIN="${VENV}/bin/python"
      log "Using existing venv"
      # Only install deps if imports are missing (avoids multi-second pip on every click).
      if ! "${PYTHON_BIN}" -c 'import fastapi, uvicorn, pydantic, certifi' >/dev/null 2>&1; then
        log "Installing missing Python packages…"
        "${PYTHON_BIN}" -m pip install -r "${ROOT}/requirements.txt" >>"${LOG_FILE}" 2>&1 || true
      fi
      return
    fi
  else
    rebuild_venv=1
  fi

  if [[ "${rebuild_venv}" -eq 1 ]]; then
    rm -rf "${VENV}"
  fi

  log "Creating virtualenv at ${VENV}"
  if "${system_python}" -m venv "${VENV}" >>"${LOG_FILE}" 2>&1 \
    && [[ -x "${VENV}/bin/python" ]]; then
    PYTHON_BIN="${VENV}/bin/python"
  else
    log "venv failed; falling back to user site packages in Application Support"
    rm -rf "${VENV}"
    local py_user="${APP_SUPPORT}/python-packages"
    mkdir -p "${py_user}"
    export PYTHONPATH="${py_user}${PYTHONPATH:+:${PYTHONPATH}}"
    export PYTHONUSERBASE="${APP_SUPPORT}/python-user"
    mkdir -p "${PYTHONUSERBASE}"
    if ! "${system_python}" -m pip install --upgrade pip >>"${LOG_FILE}" 2>&1; then
      die "This Python install cannot create a virtual environment or use pip.

Install the official Python package from https://www.python.org/downloads/macos/
Then open MessageManager again.

Details: ${LOG_FILE}"
    fi
    "${system_python}" -m pip install --target "${py_user}" -r "${ROOT}/requirements.txt" >>"${LOG_FILE}" 2>&1 \
      || die "Could not install Python dependencies.

Install Python from https://www.python.org/downloads/macos/ and try again.

Details: ${LOG_FILE}"
    PYTHON_BIN="${system_python}"
    export THREAD_LEDGER_PYTHONPATH="${py_user}"
    return
  fi

  "${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "${PYTHON_BIN}" -m pip install -r "${ROOT}/requirements.txt" >>"${LOG_FILE}" 2>&1 \
    || die "Could not install Python dependencies. See ${LOG_FILE}.

If this keeps failing, install Python from https://www.python.org/downloads/macos/"
}

bundled_version() {
  local ver_file="${ROOT}/../VERSION"
  if [[ -f "${ver_file}" ]]; then
    tr -d '[:space:]' <"${ver_file}"
    return
  fi
  if [[ -f "${ROOT}/VERSION" ]]; then
    tr -d '[:space:]' <"${ROOT}/VERSION"
    return
  fi
  echo ""
}

running_version() {
  curl -sf "${URL}/api/version" 2>/dev/null \
    | python3 -c 'import sys,json; print(json.load(sys.stdin).get("version") or "")' 2>/dev/null \
    || true
}

server_up() {
  curl -sf "${URL}/api/health" >/dev/null 2>&1
}

stop_server() {
  if [[ -f "${PID_FILE}" ]]; then
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      log "Stopping server pid ${pid}"
      kill "${pid}" 2>/dev/null || true
      sleep 0.3
      kill -9 "${pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
  fi
  # Also stop any leftover listener on our port (stale upgrade).
  # Keep this bounded — unbounded lsof has hung Dock launches before.
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(perl -e 'alarm 2; exec @ARGV' lsof -nP -t -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  if [[ -n "${pids}" ]]; then
    log "Stopping leftover listeners on ${PORT}: ${pids}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 0.2
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
}

can_read_messages_db() {
  local py="$1"
  [[ -x "${py}" ]] || return 1
  # Prefer the cache created by the native app launcher (FDA applies there).
  # THREAD_LEDGER_MESSAGES_CACHE may be a directory or a chat.db file path.
  local cache_root="${THREAD_LEDGER_MESSAGES_CACHE:-${APP_SUPPORT}/messages-cache}"
  if [[ -f "${cache_root}" ]]; then
    return 0
  fi
  if [[ -f "${cache_root}/chat.db" ]]; then
    return 0
  fi
  "${py}" - <<'PY' >/dev/null 2>&1
from pathlib import Path
import shutil, tempfile
src = Path.home() / "Library" / "Messages" / "chat.db"
if not src.exists():
    raise SystemExit(0)
td = Path(tempfile.mkdtemp())
try:
    shutil.copy2(src, td / "chat.db")
except PermissionError:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

start_server() {
  # Always restart so upgrades / FDA / Python switches take effect immediately.
  # Reusing a stale CLT Python server was leaving chat.db unreadable after install.
  log "Preparing server…"
  stop_server
  rm -f "${PID_FILE}"

  if [[ -x "${VENV}/bin/python" ]] && python_usable "${VENV}/bin/python"; then
    PYTHON_BIN="${VENV}/bin/python"
  fi

  if ! can_read_messages_db "${PYTHON_BIN}"; then
    log "WARN: ${PYTHON_BIN} cannot read chat.db — preferring Framework Python + fresh venv"
    local framework
    if framework="$(
      for c in \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.9/bin/python3
      do
        if python_usable "${c}"; then echo "${c}"; exit 0; fi
      done
      exit 1
    )"; then
      rm -rf "${VENV}"
      if "${framework}" -m venv "${VENV}" >>"${LOG_FILE}" 2>&1 \
        && [[ -x "${VENV}/bin/python" ]]; then
        PYTHON_BIN="${VENV}/bin/python"
        "${PYTHON_BIN}" -m pip install --upgrade pip >/dev/null 2>&1 || true
        "${PYTHON_BIN}" -m pip install -r "${ROOT}/requirements.txt" >>"${LOG_FILE}" 2>&1 || true
        log "Recreated venv with ${framework}"
      fi
    fi
  fi

  log "Starting server on ${PORT} with ${PYTHON_BIN} (bundle v$(bundled_version))"
  (
    cd "${ROOT}"
    if [[ -n "${THREAD_LEDGER_PYTHONPATH:-}" ]]; then
      export PYTHONPATH="${THREAD_LEDGER_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
    fi
    # Detach fully so closing the keep-alive UI can't kill the server process group.
    nohup "${PYTHON_BIN}" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT}" \
      >>"${SERVER_LOG}" 2>&1 &
    echo $! >"${PID_FILE}"
  )
  disown >/dev/null 2>&1 || true

  for _ in $(seq 1 40); do
    if server_up; then
      log "Server ready v$(running_version) via ${PYTHON_BIN} (pid $(cat "${PID_FILE}" 2>/dev/null || echo '?'))"
      return
    fi
    sleep 0.25
  done
  die "Server failed to start. See ${SERVER_LOG} and ${LOG_FILE}."
}

run_keepalive() {
  # Tk on Apple CLT Python often crashes ("Python quit unexpectedly"). Prefer a
  # headless keep-alive; users can Quit from the browser footer.
  log "Using headless keep-alive (browser Quit stops the server)"
  return 2
}

wait_until_server_stops() {
  log "Falling back to headless keep-alive (quit from the browser Quit button or stop the process)"
  osascript -e "display notification \"MessageManager is running at ${URL}. Use Quit in the browser footer, or reopen the app to stop.\" with title \"MessageManager\"" >/dev/null 2>&1 || true
  while server_up; do
    sleep 2
  done
  log "Server stopped (headless keep-alive ending)"
}

setup_runtime
start_server
# Bring the UI forward; retry once if the first open is ignored.
open "${URL}" || true
sleep 0.35
open "${URL}" || true
osascript -e "display notification \"MessageManager is ready\" with title \"MessageManager\"" >/dev/null 2>&1 || true

# AppleScript display dialogs often fail or auto-dismiss from a shell .app.
# Prefer headless keep-alive; users can Quit from the browser footer.
if run_keepalive; then
  stop_server
  log "Quit via keep-alive window"
else
  wait_until_server_stops
  stop_server
fi
