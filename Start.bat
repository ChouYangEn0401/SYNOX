@echo off
rem Start.bat -- start SYNOX in a visible, minimized window (close the window or run Stop.bat to stop).
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist "%VENV_PY%" goto notinstalled
if not exist "%~dp0config.json" goto notinstalled
if /i "%~1"=="--here" goto run
rem --no-browser (autostart at login): web-only mode does not pop up the browser; inherited by the window below.
if /i "%~1"=="--no-browser" set "SYNOX_NO_BROWSER=1"
start "SYNOX" /min "%ComSpec%" /c ""%~f0" --here"
exit /b 0
:run
title SYNOX
"%VENV_PY%" -m synox run
if errorlevel 1 pause
exit /b
:notinstalled
echo [X] SYNOX is not set up yet. Double-click Setup.bat first.
pause
exit /b 1
