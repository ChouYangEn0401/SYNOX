@echo off
rem Console.bat -- talk to SYNOX in this window without Telegram (for trying things and troubleshooting).
rem Type /help ; !N presses button N ; :q quits. Schedules do not run in this mode.
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist "%VENV_PY%" (
  echo [X] SYNOX is not set up yet. Double-click Setup.bat first.
  pause
  exit /b 1
)
chcp 65001 >nul
"%VENV_PY%" -m synox console %*
pause
