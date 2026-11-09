@echo off
rem Setup.bat -- double-click to install SYNOX. Safe to run again (re-runs the wizard).
rem Only calls setup\bootstrap.ps1: find or install Python 3.11+, create .venv, pip install, open the wizard.
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
echo SYNOX setup: preparing Python and packages, please wait...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\bootstrap.ps1"
if errorlevel 1 (
  echo.
  echo [X] Setup did not finish. See the messages above.
  pause
  exit /b 1
)
exit /b 0
