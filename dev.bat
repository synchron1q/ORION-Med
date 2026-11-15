@echo off
rem ORION-MED // HEV-1 - Hot-Reload Development Mode (Backend :8000 + Vite Dev :5173)
setlocal
cd /d "%~dp0"
if not exist "%~dp0backend\.venv\Scripts\python.exe" (
  echo [HEV-1] Run setup.bat first.
  exit /b 1
)
if exist "%ProgramFiles%\Microsoft Visual Studio\18\Professional\MSBuild\Microsoft\VisualStudio\NodeJs\npm.cmd" (
  set "PATH=%ProgramFiles%\Microsoft Visual Studio\18\Professional\MSBuild\Microsoft\VisualStudio\NodeJs;%PATH%"
)
start "ORION-MED Backend (:8000)" /D "%~dp0backend" "%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
start "ORION-MED Frontend Dev (:5173)" /D "%~dp0frontend" cmd /k "npm run dev"
timeout /t 3 >nul
start http://localhost:5173
