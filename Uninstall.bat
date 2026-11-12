@echo off
rem Uninstall.bat -- remove what Setup.bat added (shortcuts, startup entry, .synoxpack association, .venv...).
rem   Uninstall.bat            menu (check / shortcuts / env / all)
rem   Uninstall.bat check      only list what is installed
rem   Uninstall.bat env -Yes   non-interactive (modes: check, shortcuts, env, all)
rem Never deletes the SYNOX folder itself. ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0"
set "MODE_ARG="
if not "%~1"=="" set "MODE_ARG=-Mode %~1"
set "YES_ARG="
if /i "%~2"=="-Yes" set "YES_ARG=-Yes"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1" %MODE_ARG% %YES_ARG%
set "RC=%errorlevel%"
echo.
pause
exit /b %RC%
