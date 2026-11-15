@echo off
rem ORION-MED // HEV-1 - one-time setup on Windows (Python 3.12+ and Node.js 20.19+/22.12+ required)
setlocal
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY set "PY=python"
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" || (
  echo [HEV-1] Python 3.12+ is required: https://www.python.org/downloads/
  exit /b 1
)
where npm >nul 2>&1 || (
  echo [HEV-1] Node.js is required: https://nodejs.org/
  exit /b 1
)
echo [HEV-1] Creating Python virtual environment...
%PY% -m venv backend\.venv || exit /b 1
backend\.venv\Scripts\python -m pip install --upgrade pip
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt || exit /b 1
echo [HEV-1] Installing and building the crew interface...
pushd frontend
call npm install || (popd & exit /b 1)
call npm run build || (popd & exit /b 1)
popd
echo.
echo [HEV-1] Setup complete. Start the system with run.bat
