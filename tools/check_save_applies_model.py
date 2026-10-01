"""真实验证 v2.6.4：在真实 MainWindow 上跑一遍「改模型 → 保存 → Runner 用新模型」。

用真实控件、真实 _on_save、真实 build_default_runner，只把 QMessageBox 打掉。
这是单元测试之外的端到端证明。

不发送任何微信消息（不启动循环），只验证 Runner 实例与配置。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import wxbot.gui as gui  # noqa: E402
import wxbot.config as cfg_mod  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

FAILURES: list[str] = []
LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "save_model_check.txt"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_log = LOG_PATH.open("w", encoding="utf-8")


def print(*args, **kwargs) -> None:  # noqa: A001
    """同时写控制台和日志文件（崩溃时也能看到跑到哪）。"""
    _log.write(" ".join(str(a) for a in args) + "\n")
    _log.flush()
    __builtins__["print"](*args, **kwargs) if isinstance(__builtins__, dict) else __builtins__.print(*args, **kwargs)


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        FAILURES.append(label)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    import tempfile

    tmp = tempfile.TemporaryDirectory()
    real_path = cfg_mod.DEFAULT_CONFIG_PATH
    cfg_path = Path(tmp.name) / "config.toml"
    cfg_mod.DEFAULT_CONFIG_PATH = cfg_path

    # 所有弹窗都吞掉，避免脚本卡住
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)

    try:
        cfg = AppConfig()
        cfg.llm.provider = "lmstudio"
        cfg.llm.base_url = "http://127.0.0.1:1234/v1"
        cfg.llm.model = "qwen/qwen3.5-9b"     # 起点：旧模型
        cfg.llm.timeout_sec = 600.0
        cfg.whitelist.chats = ("测试会话",)
        cfg_path.write_text(cfg_mod.dump_config_text(cfg), encoding="utf-8")
        # ⚠ 必须同时改 gui 里的那份绑定：`gui.py` 是 `from .config import
        # DEFAULT_CONFIG_PATH`（模块级绑定），只改 cfg_mod 的话 _on_save 仍会
        # 写到**真实 config.toml** —— 这个坑我自己踩过一次，把用户配置写坏了。
        gui.DEFAULT_CONFIG_PATH = cfg_path
        gui.load_config = lambda *a, **k: cfg_mod.load_config(cfg_path)

        window = gui.MainWindow()
        window.show()
        app.processEvents()

        print("=== 起点 ===")
        check(window.model_combo.currentText() == "qwen/qwen3.5-9b",
              f"界面加载出旧模型：{window.model_combo.currentText()}")

        # 1) 手动开一次循环，让 Runner 真实存在并运行
        window.run_switch.setChecked(True)
        window._on_run_switch(True)
        app.processEvents()
        runner_before = window._runner
        check(runner_before is not None and runner_before.running, "循环已启动")
        check(runner_before._config.llm.model == "qwen/qwen3.5-9b",
              f"Runner 启动时用旧模型：{runner_before._config.llm.model}")

        # 2) 在界面上换模型（模拟用户在下拉框里改）
        window.model_combo.setEditText("minicpm-v-4.6")
        app.processEvents()
        check(window.model_combo.currentText() == "minicpm-v-4.6",
              f"界面已换成新模型：{window.model_combo.currentText()}")
        print("  → 此时（保存前）Runner 仍是旧模型："
              f"{runner_before._config.llm.model}   ← 这就是 bug 本身")

        # 3) 点「保存配置」—— 走真实 _on_save
        window._on_save()
        app.processEvents()

        print("\n=== 保存后 ===")
        runner_after = window._runner
        check(runner_after is not None, "保存后仍有 Runner")
        check(runner_after is runner_before,
              "Runner 实例没被重建（v2.6.5：重建会触发 WGC 原生崩溃，改为热更新）")
        check(runner_after._config.llm.model == "minicpm-v-4.6",
              f"✅ Runner 用上新模型：{runner_after._config.llm.model}")
        check(runner_after._pipeline._config.llm.model == "minicpm-v-4.6",
              "pipeline 也换到了新配置（否则生成仍用旧模型）")
        check(runner_after.running, "循环一直在跑（没有被 stop/start）")
        check(window.run_switch.isChecked(), "界面开关仍显示运行中")

        # 4) 磁盘也跟着更新了
        on_disk = cfg_mod.load_config(cfg_path)
        check(on_disk.llm.model == "minicpm-v-4.6",
              f"磁盘配置也是新模型：{on_disk.llm.model}")

        # 5) 换回去再验证一次（不是一次性巧合）
        window.model_combo.setEditText("google/gemma-4-e2b")
        app.processEvents()
        window._on_save()
        app.processEvents()
        check(window._runner._config.llm.model == "google/gemma-4-e2b",
              f"第二次换模型也生效：{window._runner._config.llm.model}")

        # 6) 磁盘也跟着更新了
        check(
            cfg_mod.load_config(cfg_path).llm.model == "google/gemma-4-e2b",
            "临时配置文件也是新值（真实 config.toml 未被触碰）",
        )

        # 收尾：先停循环再关窗。离屏模式下反复 start/stop 会让 WGC 原生代码
        # 在退出时竞态崩溃（0xC0000005），所以只做一次干净的停。
        window._on_run_switch(False)
        app.processEvents()
        check(not (window._runner and window._runner.running), "循环已干净停止")
        window.close()
        app.processEvents()
    finally:
        cfg_mod.DEFAULT_CONFIG_PATH = real_path
        tmp.cleanup()

    print()
    if FAILURES:
        print(f"共 {len(FAILURES)} 项未通过：")
        for item in FAILURES:
            print("  - " + item)
        return 1
    print("全部通过：改模型 → 保存 → 运行中的循环立刻用上新模型。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())