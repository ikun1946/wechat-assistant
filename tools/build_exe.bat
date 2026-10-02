@echo off
rem 一键打包成单文件 exe：dist\微信自动回复助手.exe
rem 用法：双击本文件，或在命令行里 tools\build_exe.bat
setlocal
cd /d "%~dp0.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo 找不到虚拟环境里的 python：%PY%
    echo 请先运行：uv venv --python 3.12
    exit /b 1
)

echo [1/3] 确认 PyInstaller ...
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo   没装 PyInstaller，正在安装 ...
    set "VIRTUAL_ENV=%CD%\.venv"
    uv pip install pyinstaller || goto :fail
)

echo [2/3] 清理旧的构建产物 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 开始打包（第一次会比较久，要一两分钟）...
"%PY%" -m PyInstaller wxbot.spec --noconfirm --clean || goto :fail

echo.
echo 打包完成：dist\微信自动回复助手.exe
echo.
echo 首次运行会在 exe 旁边生成 config.toml 和 data\ 目录。
echo 想让它开机自启：把 exe 复制到启动文件夹，或用「任务计划程序」。
echo.
pause
exit /b 0

:fail
echo.
echo 打包失败，请看上面的报错。
pause
exit /b 1
