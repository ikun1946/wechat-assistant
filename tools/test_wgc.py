"""WGC（Windows Graphics Capture）后台截屏测试 v2：按 HWND 捕获微信窗口。

用法：.venv/Scripts/python.exe tools/test_wgc.py
只读：不点击、不输入、不发送、不抢前台。
唯一动作：若微信窗口处于隐藏/最小化状态，先把它显示出来（等同点托盘图标），否则 WGC 无帧可抓。

要点：
- WGC 可以捕获被其它窗口遮挡的窗口，但不能捕获已隐藏/最小化的窗口；
- 按 HWND（window_hwnd）捕获比按标题（window_name）可靠。

输出：logs/capture_wgc.png + OCR 结果
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat import window_check

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

_user32 = ctypes.windll.user32
_user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.ShowWindow.restype = ctypes.c_bool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "logs"
OUT_PNG = OUT_DIR / "capture_wgc.png"

MAIN_TITLES = {"微信", "Weixin", "WeChat"}


def find_main_window() -> dict | None:
    for win in window_check.find_wechat_windows():
        if win["title"].strip() in MAIN_TITLES:
            return win
    return None


def ensure_window_available(hwnd: int) -> None:
    for _ in range(6):
        win = find_main_window()
        if win and win["visible"]:
            print("[wgc] 窗口可见，开始捕获")
            return
        print("[wgc] 窗口处于隐藏/最小化，尝试显示（等同点托盘图标）...")
        _user32.ShowWindow(ctypes.c_void_p(hwnd), 5)  # SW_SHOW
        _user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
        time.sleep(1.0)
    print("[wgc] 窗口仍不可见，捕获可能失败")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = find_main_window()
    if not target:
        print("[wgc] 未找到微信窗口")
        return 2
    hwnd = int(target["hwnd"])
    print(
        f"[wgc] 目标窗口: pid={target['pid']} hwnd={hwnd} "
        f"title={target['title']!r} visible={target['visible']}"
    )
    ensure_window_available(hwnd)

    try:
        from windows_capture import WindowsCapture
    except ImportError:
        print("[wgc] windows-capture 未安装：uv pip install windows-capture")
        return 3

    state: dict = {}
    try:
        capture = WindowsCapture(window_hwnd=hwnd, draw_border=False, cursor_capture=False)
    except TypeError:
        capture = WindowsCapture(window_hwnd=hwnd)

    @capture.event
    def on_frame_arrived(frame, capture_control):
        try:
            if hasattr(frame, "save_as_image"):
                frame.save_as_image(str(OUT_PNG))
            else:
                import cv2

                cv2.imwrite(str(OUT_PNG), frame.frame_buffer)
            state["saved"] = True
        except Exception as exc:  # noqa: BLE001
            state["save_error"] = repr(exc)
        finally:
            capture_control.stop()

    @capture.event
    def on_closed():
        state["closed"] = True

    def run():
        try:
            capture.start()
        except Exception as exc:  # noqa: BLE001
            state["error"] = repr(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=15)

    if state.get("error"):
        print(f"[wgc] 捕获出错: {state['error']}")
        return 4
    if state.get("save_error"):
        print(f"[wgc] 保存帧出错: {state['save_error']}")
        return 6
    if not OUT_PNG.exists():
        print("[wgc] 15 秒内未拿到帧")
        return 5
    print(f"[wgc] 已拿到帧: {OUT_PNG}")

    import cv2
    from rapidocr_onnxruntime import RapidOCR

    img = cv2.imread(str(OUT_PNG))
    if img is None:
        print("[wgc] 读取截图失败")
        return 7
    print(f"[wgc] 图像尺寸: {img.shape}, 灰度均值 {float(img.mean()):.1f}, std {float(img.std()):.1f}")

    engine = RapidOCR()
    result, _ = engine(img)
    count = len(result) if result else 0
    print(f"[wgc] OCR 识别到 {count} 条文本")
    for item in (result or [])[:30]:
        box, text, score = item[0], item[1], item[2]
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        cx = int(sum(xs) / len(xs))
        cy = int(sum(ys) / len(ys))
        print(f"    ({cx:4d},{cy:4d}) score={float(score):.2f}  {text}")
    if count >= 3:
        print("[wgc] 通过：WGC 后台截屏可用")
    else:
        print("[wgc] 未读到内容：WGC 方案需调整或放弃")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
