@echo off
rem Update.bat -- update SYNOX to the newest stable release, or go back to the previous one (docs/adr/0023).
rem   Update.bat                  check, show what changed, ask once, download + verify, stop SYNOX, swap the program
rem                               files, reinstall packages only if they changed, start SYNOX again
rem   Update.bat -Rollback        go back to the previous version (the newest folder in _previous\, 2 are kept)
rem   Update.bat -AllowUnsigned   also accept a release without a signature (then only HTTPS + GitHub's SHA256SUMS.txt
rem                               are checked; without this switch an unsigned release is NOT installed)
rem   Update.bat -Yes             do not ask again
rem   Update.bat -FromZip <full path of a ZIP> [-AllowUnsigned]
rem                               TEST an update before a real release exists: use a SYNOX ZIP on this
rem                               computer instead of GitHub (scripts/make_update_testkit.py makes one).
rem                               SHA256SUMS.txt next to the ZIP must match when it is there; unsigned
rem                               only with -AllowUnsigned; same _previous backup and rollback
rem                               (docs/release-playbook.md)
rem   Update.bat -IncludePrerelease  this time also take a preview (alpha/beta) when it is newer than the newest stable
rem                               release; same SHA256SUMS.txt and signature checks
rem Never touches config.json, data\, packs\ (or .venv\, runtime\, lang.txt). No admin. By default only the stable
rem release is offered; previews only with -IncludePrerelease or when the settings card "also tell me about previews"
rem is on (config.json updates.channel = preview). Installed with git: use "git pull" instead (this script says so).
rem All the work is in setup\update.ps1 (downloading and checking: python -m synox update --prepare).
rem This file is itself replaced while it runs, and cmd.exe reads a .bat file line by line: so everything after
rem setlocal is ONE line on purpose (a line cmd.exe has already read keeps working after the file is swapped).
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
setlocal
cd /d "%~dp0" & call "%~dp0setup\clean-python-env.bat" & powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\update.ps1" %* & if errorlevel 1 (echo. & pause & exit /b 1) else (exit /b 0)
