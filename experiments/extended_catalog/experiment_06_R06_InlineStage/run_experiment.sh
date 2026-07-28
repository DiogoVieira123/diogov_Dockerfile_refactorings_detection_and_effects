#!/bin/sh
# Replication entry point — identical in every experiment of this catalogue:
#     sh run_experiment.sh
# This experiment measures its four indicators through verify_catalog.py, which
# rebuilds both states with --no-cache and compares each delta against the
# recorded values. See ../README.md for prerequisites and pinning mechanisms.
set -eu

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "python 3 is required (pip install dockerfile-parse)" >&2
    exit 1
fi

exec "$PY" verify_catalog.py
