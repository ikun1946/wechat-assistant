@echo off
rem wxbot GUI launcher - double-click to open the settings window
rem (uses the uv-managed base pythonw to avoid a console window; falls back to the venv shim)
cd /d "%~dp0"
set "PYW=%APPDATA%\uv\python\cpython-3.12-windows-x86_64-none\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
set "VIRTUAL_ENV=%~dp0.venv"
set "PYTHONPATH=%~dp0.venv\Lib\site-packages"
start "" "%PYW%" -m wxbot gui
