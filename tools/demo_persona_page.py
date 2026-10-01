"""人设页演示：填一份示例人设，截图 + 打印实时预览（用于自检）。

用法：.venv/Scripts/python.exe tools/demo_persona_page.py
产出：prototype/shots/persona-filled.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from wxbot.gui import MainWindow  # noqa: E402

IDENTITY = "我是阿哲，30 岁，做游戏开发，住在杭州；随和但不爱寒暄"
DESCRIPTION = "说话简短、口语化，偶尔用「～」，不用书面语"
CATCH = "哈哈哈,emmm,行吧"
AVOID = "长篇大论,说教,提自己是AI,发广告"


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.resize(1180, 1040)
    window.show()
    app.processEvents()
    window._select_page("persona")

    window.persona_identity_edit.setPlainText(IDENTITY)
    window.persona_edit.setPlainText(DESCRIPTION)
    window.persona_tone_combo.setCurrentIndex(window.persona_tone_combo.findData("humorous"))
    window.persona_length_combo.setCurrentIndex(window.persona_length_combo.findData("very_short"))
    window.persona_formality.setValue(10)
    window.persona_catch_edit.setText(CATCH)
    window.persona_avoid_edit.setText(AVOID)
    app.processEvents()

    out = Path(__file__).resolve().parents[1] / "prototype" / "shots" / "persona-filled.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    window.grab().save(str(out))
    print(f"saved: {out}")
    print("--- 实时预览（AI 实际收到的人设指令）---")
    print(window.persona_preview.toPlainText())

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
