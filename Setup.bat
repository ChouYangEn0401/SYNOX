@echo off
rem Setup.bat -- double-click to install SYNOX. Safe to run again (re-runs the wizard).
rem Only calls setup\bootstrap.ps1: get Python, create .venv, pip install, register the
rem .synoxpack file type for this Windows user (HKCU only, no admin: icon + double-click = Install-Pack.bat;
rem prints every key it writes; Uninstall.bat removes it), open the wizard.
rem The first question is the language (Enter = the Windows display language; saved in lang.txt; Setup.bat -Lang en
rem skips it). Then it says plainly that SYNOX uses its own Python and asks one question: Enter = recommended
rem (just SYNOX itself + start at sign-in; tools are picked after the tutorial), C = custom (start at sign-in,
rem Claude Code, every tool). Setup.bat -Custom goes straight to the custom list. All messages, in every
rem language, live in setup\lang\*.psd1 and the wizard. ASCII-only on purpose: cmd.exe reads .bat files in the
rem console code page.
rem Python: by default SYNOX uses its OWN private Python inside this folder (runtime\python: the installer's copy, or
rem the same CPython build downloaded from python-build-standalone, pinned URL + SHA256, unpacked with Windows'
rem own tar.exe). It never changes PATH, the registry (except the HKCU .synoxpack keys above), Conda or any other
rem Python, and needs no admin. The .venv is made with plain "python -m venv". Uninstall.bat env removes both.
rem Advanced: Setup.bat -UseSystemPython uses a Python already on this PC instead (py launcher, PATH, winget;
rem never the Microsoft Store alias). Options can be combined: Setup.bat -Lang en -Custom -UseSystemPython
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
