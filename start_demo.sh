#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3.10 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON=python3.10
elif command -v python3 >/dev/null 2>&1; then
    BOOTSTRAP_PYTHON=python3
else
    echo "Python 3.10 was not found. Install Python 3.10 and rerun this launcher." >&2
    exit 2
fi
if [ "$#" -eq 0 ]; then
    set -- --setup
fi
export PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1
exec "$BOOTSTRAP_PYTHON" -B "$SCRIPT_DIR/scripts/start_demo.py" "$@"
