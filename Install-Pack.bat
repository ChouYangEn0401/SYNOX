@echo off
rem Install-Pack.bat -- install a .synoxpack (double-click a .synoxpack file, or drag one onto this file).
rem Runs the SYNOX safety checks first (declaration, static scan); the pack is only installed after you approve:
rem if SYNOX is running, the web settings page opens with the report and a confirm button.
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
call "%~dp0setup\clean-python-env.bat"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if not exist "%VENV_PY%" goto notinstalled
if "%~1"=="" goto usage
"%VENV_PY%" -m synox install "%~1"
echo.
pause
exit /b
:usage
echo Drag a .synoxpack file onto Install-Pack.bat, or double-click the .synoxpack file.
pause
exit /b 1
:notinstalled
echo [X] SYNOX is not set up yet. Double-click Setup.bat first.
pause
exit /b 1
