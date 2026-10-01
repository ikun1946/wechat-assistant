"""发送流程测试（全部用 mock，不点击、不发送）。

锁住三件安全关键行为：
1) 顺序与还原：置前 → 点击 → 输入 → 回车 → 还原光标与原来的前台窗口；
2) 标题不符就中止，且不会输入/回车；
3) 输入框里没确认到文字就不按回车（绝不盲发）。
"""

from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from wxbot.wechat import input as input_mod
from wxbot.wechat import vision_client as vc

# 三个区域各用一种底色标识。
# 早先这里靠"图片高度"猜是哪个区域（height<=60 是标题栏、>200 是聊天区），
# 但 `pad_for_ocr` 会把扁长区域补成正方形，高度就变了 → 猜测失效、测试假红。
# 颜色是内容属性，补白不会改变它，比高度可靠。
COLOR_HEADER = (12, 20, 28)
COLOR_CHAT = (40, 60, 80)
COLOR_INPUT = (90, 110, 130)


def paint_regions(frame: np.ndarray) -> None:
    """把测试帧的三个区域涂成不同底色，供假 OCR 识别。"""
    height, width = frame.shape[:2]
    panel = int(width * vc.SESSION_LIST_WIDTH_RATIO)
    frame[int(height * 0.05) : int(height * 0.13), panel : panel + 320] = COLOR_HEADER
    frame[int(height * 0.14) : int(height * 0.72), panel:] = COLOR_CHAT
    frame[int(height * 0.76) : int(height * 0.94), panel:] = COLOR_INPUT


def fake_ocr(holder: dict):
    """按区域底色返回不同文本的假 OCR；holder 可被测试中途修改（模拟切换会话后标题变化）。"""

    def _ocr(image):
        # 补白用的是区域自身的中位色，所以整张图（补白+内容）的中位色就是区域标识色
        color = tuple(
            int(round(float(np.median(image[:, :, channel])))) for channel in range(3)
        )
        if color == COLOR_HEADER:
            text = holder.get("header", "")
        elif color == COLOR_INPUT:
            text = holder.get("input", "")
        else:
            text = holder.get("chat", "")
        height, width = image.shape[:2]
        box = [[10, 5], [90, 5], [90, height - 5], [10, height - 5]]
        return ([[box, text, 0.99]] if text else []), 0.01

    return _ocr


class SendFlowTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((641, 882, 3), 240, dtype=np.uint8)
        paint_regions(self.frame)
        self.calls: list[str] = []
        self.holder = {"header": "", "input": "", "chat": ""}

    def _client(self, *, header: str, input_text: str = "", chat_text: str = ""):
        self.holder.update(header=header, input=input_text, chat=chat_text)
        client = vc.VisionClient(ocr=fake_ocr(self.holder))
        client._window = lambda: {"hwnd": 111, "title": "微信"}  # type: ignore[assignment]
        rows = [vc.SessionRow(name="文件传输助手", preview="你好", y_center=235)]
        client.read_sessions = lambda image=None: rows  # type: ignore[assignment]
        return client

    def _patch(self, *, on_row_click=None):
        """打桩：抓屏、前台、点击、粘贴、回车、校验 —— 并记录调用顺序。"""
        grab = mock.Mock(side_effect=lambda hwnd, frames=1, **kw: self.frame)
        fg = mock.Mock(side_effect=lambda hwnd: (self.calls.append("set_foreground"), True)[1])

        def _click(x, y, **kw):
            self.calls.append("click")
            if on_row_click is not None:
                on_row_click()

        click = mock.Mock(side_effect=_click)
        paste = mock.Mock(side_effect=lambda **kw: self.calls.append("paste"))
        enter = mock.Mock(side_effect=lambda **kw: self.calls.append("enter"))
        set_cursor = mock.Mock(side_effect=lambda x, y: self.calls.append("set_cursor"))
        clipboard_set = mock.Mock(return_value=True)
        clipboard_get = mock.Mock(return_value="")
        type_unicode = mock.Mock(side_effect=lambda text, **kw: self.calls.append("type"))
        ensure = mock.Mock(return_value=True)
        get_fg = mock.Mock(return_value=999)  # 用户原本在看别的窗口
        cursor = mock.Mock(return_value=(100, 200))
        idle = mock.Mock(return_value=True)  # 测试里不真的等用户空闲

        patches = [
            mock.patch.object(vc, "grab_bgr", grab),
            mock.patch.object(vc, "ensure_window_visible", ensure),
            mock.patch.object(input_mod, "set_foreground", fg),
            mock.patch.object(input_mod, "click", click),
            mock.patch.object(input_mod, "paste", paste),
            mock.patch.object(input_mod, "press_enter", enter),
            mock.patch.object(input_mod, "set_clipboard_text", clipboard_set),
            mock.patch.object(input_mod, "get_clipboard_text", clipboard_get),
            mock.patch.object(input_mod, "type_unicode", type_unicode),
            mock.patch.object(input_mod, "get_foreground", get_fg),
            mock.patch.object(input_mod, "cursor_pos", cursor),
            mock.patch.object(input_mod, "set_cursor_pos", set_cursor),
            mock.patch.object(input_mod, "wait_until_user_idle", idle),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return {"enter": enter, "click": click, "set_cursor": set_cursor, "fg": fg}

    def test_full_flow_with_row_switch_then_restore(self):
        """切换会话后标题变成目标 → 正常发送 → 结束后还原光标与前台窗口。"""
        def switch_chat():
            self.holder["header"] = "文件传输助手"

        client = self._client(header="张三", input_text="好的")
        mocks = self._patch(on_row_click=switch_chat)
        client._input_box_contains = lambda text: True  # type: ignore[assignment]
        client._text_appears = lambda image, text: True  # type: ignore[assignment]

        ok = client.send_text("文件传输助手", "好的")
        self.assertTrue(ok)
        self.assertEqual(mocks["enter"].call_count, 1, "应按下回车")
        self.assertEqual(mocks["click"].call_count, 2, "先点会话行、再点输入框")
        self.assertIn("set_cursor", self.calls, "发送后应还原光标位置")
        self.assertEqual(
            self.calls.count("set_foreground"), 2,
            "先置前微信，结束后再把你原来的窗口切回来",
        )

    def test_skips_row_click_when_chat_already_open(self):
        client = self._client(header="文件传输助手", input_text="好的")
        mocks = self._patch()
        client._input_box_contains = lambda text: True  # type: ignore[assignment]
        client._text_appears = lambda image, text: True  # type: ignore[assignment]

        ok = client.send_text("文件传输助手", "好的")
        self.assertTrue(ok)
        self.assertEqual(mocks["click"].call_count, 1, "会话已打开时只点输入框，不点会话行")

    def test_aborts_when_header_mismatch(self):
        # 标题始终是别人 → 切换后校验失败，不允许输入或回车
        client = self._client(header="别人", input_text="好的")
        mocks = self._patch()
        client._input_box_contains = lambda text: False  # type: ignore[assignment]

        ok = client.send_text("文件传输助手", "好的")
        self.assertFalse(ok)
        self.assertIn("不符", client.last_send_detail)
        self.assertEqual(mocks["enter"].call_count, 0, "标题不符时绝不能回车")

    def test_aborts_when_input_box_empty(self):
        client = self._client(header="文件传输助手", input_text="")
        mocks = self._patch()
        client._input_box_contains = lambda text: False  # type: ignore[assignment]

        ok = client.send_text("文件传输助手", "好的")
        self.assertFalse(ok)
        self.assertIn("没有进入输入框", client.last_send_detail)
        self.assertEqual(mocks["enter"].call_count, 0, "输入框没字时绝不能回车")

    def test_send_reports_failure_when_text_not_seen(self):
        client = self._client(header="文件传输助手", input_text="好的")
        self._patch()
        client._input_box_contains = lambda text: True  # type: ignore[assignment]
        client._text_appears = lambda image, text: False  # type: ignore[assignment]

        ok = client.send_text("文件传输助手", "好的")
        self.assertFalse(ok)
        self.assertIn("未在聊天区确认", client.last_send_detail)

    def test_missing_window_returns_false(self):
        client = vc.VisionClient(ocr=None, enable_ocr=False)
        client._window = lambda: None  # type: ignore[assignment]
        self.assertFalse(client.send_text("张三", "在的"))
        self.assertIn("未找到微信窗口", client.last_send_detail)


if __name__ == "__main__":
    unittest.main()
