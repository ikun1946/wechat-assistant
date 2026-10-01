"""界面截图工具：把真实主界面渲染成 PNG，便于评审与回归对比。

用法：
    .venv\\Scripts\\python.exe tools\\shot_gui.py out\\run-dark.png --page run --theme dark
    .venv\\Scripts\\python.exe tools\\shot_gui.py out\\all.png --page all   # 逐页导出
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from wxbot.gui import MainWindow  # noqa: E402

PAGES = ("run", "reply", "persona", "model", "skills", "logs")


def main() -> int:
    parser = argparse.ArgumentParser(description="wxbot 界面截图")
    parser.add_argument("output", help="输出 PNG 路径（--page all 时作为目录前缀）")
    parser.add_argument("--page", default="run", choices=list(PAGES) + ["all"])
    parser.add_argument("--theme", default="dark", choices=["dark", "light"])
    parser.add_argument("--size", default="1180x800")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    width, height = (int(part) for part in args.size.lower().split("x"))

    window = MainWindow()
    window._theme_name = args.theme
    window._apply_theme()
    window.resize(width, height)
    window.show()
    app.processEvents()

    targets = PAGES if args.page == "all" else (args.page,)
    for page in targets:
        window._select_page(page)
        app.processEvents()
        if args.page == "all":
            path = Path(args.output)
            out = path.with_name(f"{path.stem}-{page}-{args.theme}{path.suffix or '.png'}")
        else:
            out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        window.grab().save(str(out))
        print(f"saved: {out}")

    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
