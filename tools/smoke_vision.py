"""视觉路线冒烟测试：截取微信窗口 → OCR → 打印识别到的文字（只读）。

用法：.venv/Scripts/python.exe tools/smoke_vision.py
只点击、不输入、不发送；唯一动作：把微信窗口置前 + 截屏。

要点：
- 必须在截图/坐标调用之前声明 DPI 感知，否则高缩放下坐标和截图都会错位；
- OCR 只吃屏幕像素，所以窗口被遮挡时会截到别的画面（脚本先置前降低风险）。
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat import window_check

# DPI 感知（Per-Monitor v2），必须在任何截图之前设置
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

_user32 = ctypes.windll.user32

MAIN_TITLES = {"微信", "Weixin", "WeChat"}


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def find_main_window() -> dict | None:
    for win in window_check.find_wechat_windows():
        if win["title"].strip() in MAIN_TITLES:
            return win
    return None


def main() -> int:
    target = find_main_window()
    if not target:
        print("[smoke] 未找到微信窗口，请先启动并登录微信")
        return 2
    hwnd = int(target["hwnd"])
    print(f"[smoke] 目标窗口: pid={target['pid']} hwnd={hwnd} title={target['title']!r}")

    _user32.SetForegroundWindow(hwnd)  # 置前，降低截到其他窗口的概率（best effort）
    time.sleep(1.2)

    rect = _Rect()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        print("[smoke] GetWindowRect 失败")
        return 3
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    print(f"[smoke] 窗口区域: ({rect.left},{rect.top})-({rect.right},{rect.bottom}) 尺寸 {width}x{height}")

    import mss
    import numpy as np

    mss_class = getattr(mss, "MSS", None) or mss.mss
    with mss_class() as sct:
        shot = sct.grab({"left": rect.left, "top": rect.top, "width": width, "height": height})
    img = np.array(shot)[:, :, :3]  # BGRA -> BGR
    print(f"[smoke] 截图完成: shape={img.shape}")

    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, elapsed = engine(img)
    if not result:
        print("[smoke] OCR 未识别到任何文字")
        return 4
    print(f"[smoke] OCR 识别到 {len(result)} 条文本（显示前 60 条，格式：中心坐标 / 置信度 / 文本）：")
    for item in result[:60]:
        box, text, score = item[0], item[1], item[2]
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        cx = int(sum(xs) / len(xs))
        cy = int(sum(ys) / len(ys))
        print(f"  ({cx:4d},{cy:4d}) score={float(score):.2f}  {text}")
    print("[smoke] 通过：视觉管线（截屏+OCR）可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
