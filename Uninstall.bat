@echo off
rem Uninstall.bat -- remove what Setup.bat added (shortcuts, startup entry, .synoxpack association, .venv,
rem runtime\ = SYNOX's own private Python in runtime\python; all of it inside this folder).
rem   Uninstall.bat            menu (check / shortcuts / env / all)
rem   Uninstall.bat check      only list what is installed
rem   Uninstall.bat env -Yes   non-interactive (modes: check, shortcuts, env, all)
rem   Uninstall.bat check -Lang en   language for this run (otherwise lang.txt, otherwise it asks first)
rem Never deletes the SYNOX folder itself. ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
rem All messages, in every language, live in setup\lang\*.psd1.
setlocal
cd /d "%~dp0"
set "FIRST=%~1"
if not defined FIRST (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1"
) else if "%FIRST:~0,1%"=="-" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1" -Mode %*
)
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
