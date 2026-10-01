@echo off
rem 界面原型预览（独立于项目本体，不会修改 wxbot 任何文件）
cd /d "%~dp0.."
set "PYW=%APPDATA%\uv\python\cpython-3.12-windows-x86_64-none\pythonw.exe"
if not exist "%PYW%" set "PYW=%~dp0..\.venv\Scripts\pythonw.exe"
set "VIRTUAL_ENV=%~dp0..\.venv"
set "PYTHONPATH=%~dp0..\.venv\Lib\site-packages"
start "" "%PYW%" "%~dp0redesign_prototype.py"
