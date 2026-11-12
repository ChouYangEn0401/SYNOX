@echo off
rem Open-SYNOX.bat -- open the SYNOX web page on this computer (starts SYNOX first if it is not running).
rem Issues a fresh one-time owner login link and opens it in the default browser; no Telegram needed.
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist "%VENV_PY%" goto notinstalled
if not exist "%~dp0config.json" goto notinstalled
"%VENV_PY%" -m synox web-login
if errorlevel 1 pause
exit /b
:notinstalled
echo [X] SYNOX is not set up yet. Double-click Setup.bat first.
pause
exit /b 1
