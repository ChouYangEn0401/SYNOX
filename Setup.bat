@echo off
rem Setup.bat -- double-click to install SYNOX. Safe to run again (re-runs the wizard).
rem Only calls setup\bootstrap.ps1: find or install Python 3.11+, create .venv, pip install, register the
rem .synoxpack file type for this Windows user (HKCU only, no admin: icon + double-click = Install-Pack.bat;
rem prints every key it writes; Uninstall.bat removes it), open the wizard.
rem The first question is the language (saved in lang.txt; Setup.bat -Lang en skips it). All messages, in every
rem language, live in setup\lang\*.psd1 and the wizard. ASCII-only on purpose: cmd.exe reads .bat files in the
rem console code page.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\bootstrap.ps1" %*
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)
exit /b 0
