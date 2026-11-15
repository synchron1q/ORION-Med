#!/usr/bin/env bash
# ORION-MED // HEV-1 - start the onboard system (crew interface at http://localhost:8000)
set -euo pipefail
cd "$(dirname "$0")/backend"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
