@echo off
rem Connect-Apple.bat -- save the account for the Apple Reminders (CalDAV) pack into the SYNOX vault.
rem The app-specific password is typed here (hidden), never in the Telegram chat.
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
"%VENV_PY%" -m synox connect apple-reminders %*
pause