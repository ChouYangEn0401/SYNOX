@echo off
rem clean-python-env.bat -- every SYNOX launcher calls this (call "%~dp0setup\clean-python-env.bat") after setlocal
rem and before it runs .venv\Scripts\python.exe. It clears, for that window only, the variables that would make the
rem SYNOX Python load another Python's code or settings (Conda, PYTHONHOME, PYTHONPATH, an active virtualenv).
rem Nothing is changed for the rest of Windows, Conda or any other Python. No setlocal here on purpose: the
rem changes must stay in the caller's (local) environment. Same list as Clear-PythonEnv in setup\bootstrap.ps1.
rem ASCII-only on purpose: cmd.exe reads .bat files in the console code page.
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="
set "PYTHONUSERBASE="
set "PYTHONEXECUTABLE="
set "VIRTUAL_ENV="
set "__PYVENV_LAUNCHER__="
set "_CE_CONDA="
set "_CE_M="
for /f "delims==" %%V in ('set CONDA_ 2^>nul') do set "%%V="
set "PYTHONNOUSERSITE=1"
exit /b 0
