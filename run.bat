@echo off
rem ORION-MED // HEV-1 - start the onboard system and open the crew interface
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (
  echo [HEV-1] Run setup.bat first.
  exit /b 1
)
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000"
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
