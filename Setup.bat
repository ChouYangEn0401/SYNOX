@echo off
rem Setup.bat -- double-click to install SYNOX. Safe to run again (re-runs the wizard).
rem Only calls setup\bootstrap.ps1: get Python, create .venv, pip install, register the
rem .synoxpack file type for this Windows user (HKCU only, no admin: icon + double-click = Install-Pack.bat;
rem prints every key it writes; Uninstall.bat removes it), open the wizard.
rem The first question is the language (saved in lang.txt; Setup.bat -Lang en skips it). All messages, in every
rem language, live in setup\lang\*.psd1 and the wizard. ASCII-only on purpose: cmd.exe reads .bat files in the
rem console code page.
rem Python: by default SYNOX uses its OWN private Python inside this folder (runtime\: the installer's copy, or
rem CPython installed by a pinned, SHA256-checked uv). It never changes PATH, the registry (except the HKCU
rem .synoxpack keys above), Conda or any other Python, and needs no admin. Uninstall.bat env removes it.
rem Advanced: Setup.bat -UseSystemPython uses a Python already on this PC instead (py launcher, PATH, winget;
rem never the Microsoft Store alias). Options can be combined: Setup.bat -Lang en -UseSystemPython
rem To switch an existing install: Uninstall.bat env, then run Setup.bat again.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\bootstrap.ps1" %*
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
exit /b 0
