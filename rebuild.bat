@echo off
rem ORION-MED // HEV-1 - Rebuild production frontend bundle
setlocal
cd /d "%~dp0frontend"
if exist "%ProgramFiles%\Microsoft Visual Studio\18\Professional\MSBuild\Microsoft\VisualStudio\NodeJs\npm.cmd" (
  set "PATH=%ProgramFiles%\Microsoft Visual Studio\18\Professional\MSBuild\Microsoft\VisualStudio\NodeJs;%PATH%"
)
call npm run build
echo.
echo [HEV-1] Frontend production bundle built into frontend\dist
pause
