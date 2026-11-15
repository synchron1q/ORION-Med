@echo off
rem AI-assisted fixes (Claude, Anthropic) - see AI_ATTRIBUTION.md
rem ORION-MED // HEV-1 - Stop servers listening on ports 8000 and 5173 (including uvicorn --reload child processes)
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000, 5173 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { taskkill /PID $_ /T /F 2>$null | Out-Null }"
echo [HEV-1] Stopped servers on ports 8000 and 5173.
