#!/bin/bash
# Double-click / open in Terminal: sync Messages into MessageManager cache
# using Terminal's Full Disk Access (works on Tahoe when app FDA does not).
DIR="$(cd "$(dirname "$0")" && pwd)"
export KEEP_TERMINAL_OPEN=1
cd "${DIR}"
exec /usr/bin/env python3 "${DIR}/sync-messages-cache.py"
