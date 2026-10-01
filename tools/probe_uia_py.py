"""pywinauto(UI Automation) 只读探测：微信窗口能否被正规 UIA 客户端拿到控件树。

用法：.venv/Scripts/python.exe tools/probe_uia_py.py
只读：不点击、不输入、不发送任何东西。
唯一动作：如果微信窗口当前隐藏/最小化，会把它显示出来以便探测（不修改任何设置）。

背景：微信 4.x 默认隐藏控件树，仅在检测到「正规无障碍客户端」时可能恢复暴露。
本脚本验证：
1) Desktop(backend='uia') 能否枚举到微信窗口；
2) 挂上主窗口后能读到多少控件（丰富 vs 稀疏）；
3) 挂上后等待片刻再读一次（看控件树是否「懒加载」出现）。
"""

from __future__ import annotations

import ctypes
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat import window_check

MAIN_TITLES = {"微信", "Weixin", "WeChat"}

_user32 = ctypes.windll.user32


def window_state(hwnd: int) -> tuple[bool, bool]:
    return bool(_user32.IsWindowVisible(hwnd)), bool(_user32.IsIconic(hwnd))


def ensure_visible(hwnd: int) -> None:
    visible, iconic = window_state(hwnd)
    print(f"[probe] 窗口状态: visible={visible} iconic={iconic}")
    if not visible or iconic:
        print("[probe] 窗口被隐藏/最小化，尝试显示（SW_RESTORE）...")
        _user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        _user32.ShowWindow(hwnd, 5)  # SW_SHOW
        _user32.SetForegroundWindow(hwnd)
        time.sleep(2.5)
        visible, iconic = window_state(hwnd)
        print(f"[probe] 处理后状态: visible={visible} iconic={iconic}")


def find_main_window() -> dict | None:
    windows = window_check.find_wechat_windows()
    for win in windows:
        if win["title"].strip() in MAIN_TITLES:
            return win
    visible = [w for w in windows if w.get("visible")]
    return visible[0] if visible else (windows[0] if windows else None)


def walk(wrapper, cap: int = 300, max_depth: int = 5) -> list[tuple[int, str, str, str]]:
    lines: list[tuple[int, str, str, str]] = []
    queue: list[tuple[object, int]] = [(wrapper, 0)]
    while queue and len(lines) < cap:
        node, depth = queue.pop(0)
        try:
            info = node.element_info
            lines.append(
                (
                    depth,
                    info.control_type or "",
                    (info.name or "")[:60],
                    info.class_name or "",
                )
            )
        except Exception:
            lines.append((depth, "<read-error>", "", ""))
            continue
        if depth < max_depth:
            try:
                for child in node.children():
                    queue.append((child, depth + 1))
            except Exception:
                pass
    return lines


def main() -> int:
    target = find_main_window()
    if not target:
        print("[probe] 未找到微信窗口，请先启动并登录微信")
        return 2
    print(f"[probe] 目标窗口: pid={target['pid']} hwnd={target['hwnd']} title={target['title']!r}")
    ensure_visible(int(target["hwnd"]))

    try:
        from pywinauto import Desktop
    except ImportError:
        print("[probe] pywinauto 未安装：uv pip install pywinauto")
        return 3

    desktop = Desktop(backend="uia")

    try:
        seen = []
        for win in desktop.windows():
            try:
                info = win.element_info
                seen.append((info.control_type, info.name, info.process_id))
            except Exception:
                continue
        hits = [item for item in seen if item[2] == target["pid"]]
        print(f"[probe] Desktop().windows() 共 {len(seen)} 个窗口；属于微信进程的 {len(hits)} 个")
        for hit in hits[:10]:
            print(f"    - {hit}")
    except Exception:
        print("[probe] Desktop().windows() 枚举失败：")
        traceback.print_exc()

    try:
        win = desktop.window(handle=target["hwnd"])
        wrapper = win.wrapper_object()
        info = wrapper.element_info
        print(
            f"[probe] 已挂上窗口: control_type={info.control_type} "
            f"name={info.name!r} class={info.class_name!r}"
        )

        lines = walk(wrapper)
        print(f"[probe] 第 1 次遍历：节点数 {len(lines)}")
        for depth, control_type, name, class_name in lines:
            print(f"{'  ' * depth}{control_type} | {class_name} | {name}")

        time.sleep(1.5)
        lines2 = walk(wrapper)
        print(f"[probe] 第 2 次遍历（等 1.5s 后）：节点数 {len(lines2)}")
        if len(lines2) > len(lines):
            for depth, control_type, name, class_name in lines2:
                print(f"{'  ' * depth}{control_type} | {class_name} | {name}")

        best = max(len(lines), len(lines2))
        if best >= 50:
            print("[probe] VERDICT: 控件树较丰富 -> UIA 路线可行")
        else:
            print("[probe] VERDICT: 控件树稀疏（无子节点）-> 走视觉 OCR 路线")
    except Exception:
        print("[probe] 挂窗口/遍历失败：")
        traceback.print_exc()
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
