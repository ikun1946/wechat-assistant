"""打包成 exe 时的入口：**双击就跑图形界面**，不走 argparse。

为什么需要单独一个入口：
`main()` 的子命令是 `required=True`（`python -m wxbot gui` 必须显式给 `gui`）。
但打包后的 exe 是**双击启动、不带任何参数**的，直接复用 main() 会被 argparse
判为"缺少必填子命令"然后立刻退出 —— 表现就是"双击 exe 什么都没发生，进程秒退"。

所以这里：没参数 → 直接开界面；带了参数 → 仍然交给 main() 走命令行那套
（`微信自动回复助手.exe status` 之类照样能用）。
"""

from __future__ import annotations

import sys


def app_main() -> int:
    # ⚠ 必须用**绝对导入**。PyInstaller 会把 app_entry.py 当成顶层脚本执行，
    # 此时 `__package__` 是空的，写 `from .gui import run_gui` 会报
    # "attempted relative import with no known parent package"（实测踩过，exe 直接秒退）。
    if len(sys.argv) > 1:
        from wxbot.main import main as cli_main

        return cli_main(sys.argv[1:])
    from wxbot.gui import run_gui

    return run_gui()


if __name__ == "__main__":
    raise SystemExit(app_main())
