"""在桌面创建"微信自动回复助手"快捷方式。

目录版（onedir）比单文件更适合常驻应用：启动快、依赖加载正常。
这个脚本把 dist\\微信自动回复助手\\微信自动回复助手.exe 变成桌面上的一个图标。

用法：
    .venv\\Scripts\\python.exe tools\\make_shortcut.py            # 创建
    .venv\\Scripts\\python.exe tools\\make_shortcut.py --remove   # 删除
    .venv\\Scripts\\python.exe tools\\make_shortcut.py --startup  # 顺便放进开机启动
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "微信自动回复助手" / "微信自动回复助手.exe"
LINK_NAME = "微信自动回复助手.lnk"


def desktop_dir() -> Path:
    # OneDrive 重定向时 Get-Desktop 未必准，用注册表更可靠
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        with key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        return Path(value)
    except Exception:
        return Path.home() / "Desktop"


def startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _ps(script: str) -> None:
    import subprocess

    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())


def create(target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    link = target_dir / LINK_NAME
    # 图标指向 exe 自己（exe 里已内置图标），工作目录设为 exe 所在目录
    # —— 这样"在别处打开命令"之类不会把工作目录带偏。
    escaped_link = str(link).replace("'", "''")
    escaped_exe = str(EXE).replace("'", "''")
    workdir = str(EXE.parent).replace("'", "''")
    _ps(
        "$s = New-Object -ComObject WScript.Shell; "
        f"$l = $s.CreateShortcut('{escaped_link}'); "
        f"$l.TargetPath = '{escaped_exe}'; "
        f"$l.WorkingDirectory = '{workdir}'; "
        "$l.IconLocation = '" + str(EXE).replace("'", "''") + ",0'; "
        "$l.Description = '个人微信自动回复助手（安全优先）'; "
        "$l.Save()"
    )
    return link


def main() -> int:
    parser = argparse.ArgumentParser(description="创建/删除桌面快捷方式")
    parser.add_argument("--remove", action="store_true", help="删除快捷方式")
    parser.add_argument("--startup", action="store_true", help="同时放到开机启动目录")
    args = parser.parse_args()

    if args.remove:
        removed = 0
        for folder in (desktop_dir(), startup_dir()):
            link = folder / LINK_NAME
            if link.exists():
                link.unlink()
                print(f"已删除 {link}")
                removed += 1
        if not removed:
            print("没有找到要删除的快捷方式")
        return 0

    if not EXE.exists():
        print(f"找不到程序：{EXE}")
        print("请先运行 tools\\build_exe.bat 打包。")
        return 1

    link = create(desktop_dir())
    print(f"已在桌面创建快捷方式：{link}")

    if args.startup:
        startup = create(startup_dir())
        print(f"已加入开机启动：{startup}")
    else:
        print("如需开机自启，可加 --startup 参数（或 Win+R 输入 shell:startup 手动拖入）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
