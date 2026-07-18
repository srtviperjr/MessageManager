#!/bin/bash
# Double-clickable helper: opens Full Disk Access and reveals MessageManager.
DIR="$(cd "$(dirname "$0")" && pwd)"
export KEEP_TERMINAL_OPEN=1
exec bash "${DIR}/grant-full-disk-access.sh" "$@"
