"""可视验证：「运行」页的上下文窗口占用条 + 思考过程展示。

用假的观测数据驱动界面（不发微信消息、不调模型），把两个状态各截一张：
1) 空闲态；2) 有占用 + 有思考内容（并展开思考区）。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from wxbot.gui import MainWindow  # noqa: E402
from wxbot.runner import RunnerStats  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "prototype" / "shots"

REASONING = """Thinking Process:

1.  **Analyze the Request:**
    *   **Role:** I am acting as a WeChat reply assistant for the user.
    *   **Hard Rule:** 绝对不能说自己是 AI、机器人、助手、程序、模型或「代回复」。
    *   **Identity:** 对方问「你是谁」时，只回答「我是钱程月、王静意……」。
2.  **Check the context window:** 当前占用已经到 62%，再长就该提醒用户清理记忆了。
3.  **Draft the reply:** 保持 1~2 句、简短口语化，不解释、不否认。
"""


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window._theme_name = "dark"
    window._apply_theme()
    window.resize(1180, 900)
    window.show()
    app.processEvents()
    window._select_page("run")
    app.processEvents()

    # 1) 空闲态
    window._update_context_display(RunnerStats())
    app.processEvents()
    window.grab().save(str(OUT / "v26-run-context-idle.png"))
    print("saved: v26-run-context-idle.png")

    # 2) 有占用 + 有思考内容
    stats = RunnerStats(
        received=7,
        replied=5,
        sent=5,
        denied=2,
        polls=42,
        context_used=5093,
        context_total=8192,
        last_reasoning=REASONING,
    )
    window._update_context_display(stats)
    window.think_toggle.setChecked(True)
    app.processEvents()
    window.grab().save(str(OUT / "v26-run-context-active.png"))
    print("saved: v26-run-context-active.png")

    # 3) 快满的告警态
    window._update_context_display(replace(stats, context_used=7700))
    app.processEvents()
    window.grab().save(str(OUT / "v26-run-context-full.png"))
    print("saved: v26-run-context-full.png")

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
