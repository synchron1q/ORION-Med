#!/usr/bin/env bash
# ORION-MED // HEV-1 - one-time setup on Linux/macOS (Python 3.12+, Node.js 20.19+/22.12+)
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || { echo "Python 3.12+ required"; exit 1; }
"$PY" -m venv backend/.venv
backend/.venv/bin/python -m pip install --upgrade pip
backend/.venv/bin/python -m pip install -r backend/requirements.txt
(cd frontend && npm install && npm run build)
echo "Setup complete. Start with ./run.sh"
