@echo off
rem Stop.bat -- stop the running SYNOX bot.
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
if not exist "%VENV_PY%" (
  echo SYNOX is not installed.
  pause
  exit /b 1
)
"%VENV_PY%" -m synox stop
timeout /t 3 >nul
