"""背景截屏能力测试：验证能否在不打扰前台的情况下读到微信窗口内容。

用法：.venv/Scripts/python.exe tools/test_capture.py
只读：不点击、不输入、不发送、不抢前台。

两种方式对比：
1) PrintWindow(PW_RENDERFULLCONTENT)：即使窗口被别的窗口遮挡，也可能拿到自身画面；
2) 直接屏幕抓取：窗口被遮挡时会拿到遮挡物的画面（对照组）。
输出：两种截屏各保存一张 PNG（logs/），并各跑一次 OCR，打印识别文本数与前若干条。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.wechat import window_check

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

MAIN_TITLES = {"微信", "Weixin", "WeChat"}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "logs"


class _Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


_user32.GetWindowDC.argtypes = [wintypes.HWND]
_user32.GetWindowDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
_user32.PrintWindow.restype = wintypes.BOOL
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi32.DeleteObject.restype = wintypes.BOOL
_gdi32.DeleteDC.argtypes = [wintypes.HDC]
_gdi32.DeleteDC.restype = wintypes.BOOL


def find_main_window() -> dict | None:
    for win in window_check.find_wechat_windows():
        if win["title"].strip() in MAIN_TITLES:
            return win
    return None


def capture_printwindow(hwnd: int, width: int, height: int):
    """用 PrintWindow 抓窗口自身画面（可捕获被遮挡窗口）。返回 (BGR 图像 | None, PrintWindow 返回值)。"""
    import numpy as np

    window_dc = _user32.GetWindowDC(hwnd)
    if not window_dc:
        return None, 0
    mem_dc = _gdi32.CreateCompatibleDC(window_dc)
    bitmap = _gdi32.CreateCompatibleBitmap(window_dc, width, height)
    try:
        _gdi32.SelectObject(mem_dc, bitmap)
        ok = _user32.PrintWindow(hwnd, mem_dc, 0x00000002)  # PW_RENDERFULLCONTENT
        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = width
        header.biHeight = -height  # 负值 = 自上而下
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        got = _gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        if not got:
            return None, ok
        img = np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()
        return img, ok
    finally:
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(hwnd, window_dc)


def ocr_and_report(engine, img, tag: str) -> int:
    result, _ = engine(img)
    count = len(result) if result else 0
    print(f"[{tag}] OCR 识别到 {count} 条文本")
    for item in (result or [])[:25]:
        box, text, score = item[0], item[1], item[2]
        xs = [point[0] for point in box]
        ys = [point[1] for point in box]
        cx = int(sum(xs) / len(xs))
        cy = int(sum(ys) / len(ys))
        print(f"    ({cx:4d},{cy:4d}) score={float(score):.2f}  {text}")
    return count


def main() -> int:
    target = find_main_window()
    if not target:
        print("[capture] 未找到微信窗口")
        return 2
    hwnd = int(target["hwnd"])
    rect = _Rect()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    print(f"[capture] 微信窗口: hwnd={hwnd} rect=({rect.left},{rect.top})-({rect.right},{rect.bottom}) {width}x{height}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    import cv2
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()

    img_printwindow, ok = capture_printwindow(hwnd, width, height)
    if img_printwindow is not None:
        cv2.imwrite(str(OUT_DIR / "capture_printwindow.png"), img_printwindow)
        print(f"[capture] PrintWindow 返回 {ok}，已保存 logs/capture_printwindow.png")
        count_pw = ocr_and_report(engine, img_printwindow, "PrintWindow")
    else:
        count_pw = -1
        print(f"[capture] PrintWindow 抓取失败（ok={ok}）")

    import mss

    mss_class = getattr(mss, "MSS", None) or mss.mss
    with mss_class() as sct:
        shot = sct.grab({"left": rect.left, "top": rect.top, "width": width, "height": height})
    img_screen = np.array(shot)[:, :, :3]
    cv2.imwrite(str(OUT_DIR / "capture_screen.png"), img_screen)
    count_scr = ocr_and_report(engine, img_screen, "屏幕抓取")

    print("---- 结论 ----")
    print(f"PrintWindow 文本数: {count_pw} | 屏幕抓取文本数: {count_scr}")
    if count_pw >= 5:
        print("[capture] PrintWindow 可用：可以不抢前台、后台读取窗口画面")
    else:
        print("[capture] PrintWindow 未能读到内容：需要其它方案（前台截屏 / 窗口捕获 API）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
