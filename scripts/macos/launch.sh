#!/bin/bash
set -euo pipefail

APP_SUPPORT="${HOME}/Library/Application Support/MessageManager"
LOG_DIR="${APP_SUPPORT}/logs"
mkdir -p "${LOG_DIR}" "${APP_SUPPORT}/data"
LOG_FILE="${LOG_DIR}/launch.log"
SERVER_LOG="${LOG_DIR}/server.log"
export THREAD_LEDGER_DATA="${APP_SUPPORT}/data"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}" >/dev/null
}

die() {
  local msg="$1"
  log "ERROR: ${msg}"
  local escaped
  escaped="$(printf '%s' "${msg}" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  osascript -e "display dialog \"${escaped}\" with title \"MessageManager\" buttons {\"OK\"} default button \"OK\" with icon stop" >/dev/null 2>&1 || true
  exit 1
}

# Resolve bundled app root: .../MessageManager.app/Contents/Resources/app
ROOT="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
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

find_python() {
  local candidates=(
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.10/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.9/bin/python3"
    "/opt/homebrew/bin/python3"
    "/usr/local/bin/python3"
    "$(command -v python3 2>/dev/null || true)"
    "/usr/bin/python3"
  )
  local c
  for c in "${candidates[@]}"; do
    [[ -n "${c}" ]] || continue
    if python_usable "${c}"; then
      echo "${c}"
      return 0
    fi
  done
  return 1
}

setup_runtime() {
  local system_python
  if ! system_python="$(find_python)"; then
    die "Python 3.9+ is not installed (or only the macOS stub is present).

Install Python from https://www.python.org/downloads/macos/
(or run: xcode-select --install), then open MessageManager again."
  fi
  log "Using Python: ${system_python} ($("${system_python}" -V 2>&1))"

  if [[ -x "${VENV}/bin/python" ]] && python_usable "${VENV}/bin/python"; then
    PYTHON_BIN="${VENV}/bin/python"
    log "Using existing venv"
    return
  fi

  rm -rf "${VENV}"
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

server_up() {
  curl -sf "${URL}/api/health" >/dev/null 2>&1
}

start_server() {
  if server_up; then
    log "Server already running"
    return
  fi
  if [[ -f "${PID_FILE}" ]]; then
    old_pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
      kill "${old_pid}" 2>/dev/null || true
      sleep 0.3
    fi
    rm -f "${PID_FILE}"
  fi

  log "Starting server on ${PORT} with ${PYTHON_BIN}"
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
      log "Server ready (pid $(cat "${PID_FILE}" 2>/dev/null || echo '?'))"
      return
    fi
    sleep 0.25
  done
  die "Server failed to start. See ${SERVER_LOG} and ${LOG_FILE}."
}

stop_server() {
  if [[ -f "${PID_FILE}" ]]; then
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      log "Stopping server pid ${pid}"
      kill "${pid}" 2>/dev/null || true
      sleep 0.4
      kill -9 "${pid}" 2>/dev/null || true
    fi
    rm -f "${PID_FILE}"
  fi
}

run_keepalive() {
  local keepalive="${ROOT}/scripts/macos/keepalive.py"
  if [[ ! -f "${keepalive}" ]]; then
    log "keepalive.py missing at ${keepalive}"
    return 2
  fi
  if ! "${PYTHON_BIN}" -c 'import tkinter' >/dev/null 2>&1; then
    log "tkinter not available in ${PYTHON_BIN}"
    return 2
  fi
  log "Starting Tk keep-alive window"
  set +e
  "${PYTHON_BIN}" "${keepalive}" "${URL}" "${LOG_DIR}"
  local status=$?
  set -e
  return "${status}"
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
open "${URL}"

# AppleScript display dialogs often fail or auto-dismiss from a shell .app.
# Use a Tk window instead; fall back to waiting on the server process.
if run_keepalive; then
  stop_server
  log "Quit via keep-alive window"
else
  wait_until_server_stops
  stop_server
fi
