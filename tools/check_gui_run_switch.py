"""GUI 运行开关自检（离屏运行）：验证「点一下才工作、关了就停工」的语义。

用法：.venv/Scripts/python.exe tools/check_gui_run_switch.py
使用假客户端（NullClient），不触碰真实微信、不发送任何消息。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402
from wxbot.wechat.base import IncomingMessage, WeChatClient  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        failures.append(label)


class ScriptedClient(WeChatClient):
    """第二轮起持续报一条消息，用于验证循环确实在跑。"""

    def __init__(self):
        self.calls = 0

    @property
    def can_send(self) -> bool:
        return False

    def is_available(self) -> tuple[bool, str]:
        return True, "ok"

    def poll_new_messages(self):
        self.calls += 1
        return [IncomingMessage("张三", "在吗")]

    def send_text(self, chat_name: str, text: str) -> bool:
        return False


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    cfg = AppConfig()
    cfg.whitelist.chats = ("张三",)
    cfg.reply.rules = cfg.reply.rules  # 保持默认规则
    gui.load_config = lambda *a, **k: cfg

    client = ScriptedClient()
    original_builder = gui.build_default_runner

    def fake_builder(config, *, on_event=None, poll_interval=3.0, client=None):
        return original_builder(
            config, on_event=on_event, poll_interval=1.0, client=client or ScriptedClient()
        )

    window = gui.MainWindow()

    print("[1] 初始状态：停止")
    check(not window.run_switch.isChecked(), "滑动开关处于关闭位")
    check("已停止" in window.run_state_label.text(), "状态显示已停止")
    check("不会抓屏识别" in window.run_progress.text(), "明确说明停止时不抓屏")

    print("[2] 点一下开关 → 开始工作")
    gui.build_default_runner = lambda config, *, on_event=None, poll_interval=3.0, **kw: original_builder(
        config, on_event=on_event, poll_interval=1.0, client=ScriptedClient()
    )
    window.run_switch.setChecked(True)
    window._on_run_switch(True)
    check(window._runner is not None and window._runner.running, "Runner 已运行")
    check(window.run_switch.isChecked(), "开关显示为开启")
    check("运行中" in window.run_state_label.text(), "状态显示运行中")
    time.sleep(1.6)
    app.processEvents()
    polls = window._runner.stats.polls if window._runner else 0
    check(polls >= 1, f"后台确实在轮询（已完成 {polls} 次）")
    received = window._runner.stats.received if window._runner else 0
    check(
        window.stat_received.value_label.text() == str(received),
        f"指标卡同步（识别到 {window.stat_received.value_label.text()}）",
    )

    print("[3] 再点一下 → 停止工作")
    window.run_switch.setChecked(False)
    window._on_run_switch(False)
    check(window._runner is None, "Runner 已清空")
    check(not window.run_switch.isChecked(), "开关回到关闭位")
    check("已停止" in window.run_state_label.text(), "状态显示已停止")

    print("[4] 关闭窗口会自动停机（不留游离线程）")
    gui.build_default_runner = lambda config, *, on_event=None, poll_interval=3.0, **kw: original_builder(
        config, on_event=on_event, poll_interval=1.0, client=ScriptedClient()
    )
    window.run_switch.setChecked(True)
    window._on_run_switch(True)
    runner = window._runner
    check(runner is not None and runner.running, "重新启动成功")
    window.close()
    app.processEvents()
    check(runner is not None and not runner.running, "关窗后 Runner 已停止")
    check(window._runner is None, "关窗后引用已释放")

    print("[5] 导航与主题")
    check(window.stack.count() == 6, "共 6 个页面（运行/回复/人设/模型/技能/日志）")
    window._select_page("model")
    check("模型" in window.page_title.text(), "切换页面后标题同步")
    window._select_page("persona")
    check("人设" in window.page_title.text(), "可切到「人设」页")
    check(
        hasattr(window, "persona_preview") and bool(window.persona_preview.toPlainText()),
        "人设页有实时预览内容",
    )
    before = window._current_theme_name()
    window._on_toggle_theme()
    check(window._current_theme_name() != before, f"主题可切换（{before} → {window._current_theme_name()}）")

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("全部通过：点一下才开始工作，关了就停工。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
