"""GUI 模型页行为自检（离屏运行，断言交互是否符合预期）。

用法：.venv/Scripts/python.exe tools/check_gui_model_tab.py

检查项：
1) 切换厂商 → 地址与 Key 配置自动跟着变（不需要额外点按钮）；
2) 选择「自定义」厂商时，不清空已填写的地址；
3) 已经不存在「应用厂商预设」这种多余按钮；
4) 重新加载已保存配置时，不会被厂商默认值覆盖用户自定义的地址。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.config import AppConfig  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        failures.append(label)


def select_provider(window, key: str) -> None:
    index = window.provider_combo.findData(key)
    assert index >= 0, f"厂商 {key} 不存在"
    window.provider_combo.setCurrentIndex(index)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    # 4) 用一份「自定义 base_url」的配置构造窗口，验证不被覆盖
    custom = AppConfig()
    custom.llm.provider = "deepseek"
    custom.llm.base_url = "https://my-proxy.example.com/v1"
    custom.llm.api_key_env = "MY_OWN_KEY"
    gui.load_config = lambda *a, **k: custom
    window = gui.MainWindow()

    print("[4] 加载已保存配置时保留用户自定义地址")
    check(window.base_url_edit.text() == "https://my-proxy.example.com/v1", "地址保持用户自定义值")
    check(window.api_env_edit.text() == "MY_OWN_KEY", "Key 环境变量保持用户自定义值")

    print("[1] 切换厂商自动应用预设（不需要额外点按钮）")
    select_provider(window, "openai")
    check(window.base_url_edit.text() == "https://api.openai.com/v1", "OpenAI 地址自动填入")
    check(window.api_env_edit.text() == "OPENAI_API_KEY", "OpenAI Key 变量名自动填入")

    select_provider(window, "deepseek")
    check(window.base_url_edit.text() == "https://api.deepseek.com/v1", "DeepSeek 地址自动填入")
    check(window.api_env_edit.text() == "DEEPSEEK_API_KEY", "DeepSeek Key 变量名自动填入")

    select_provider(window, "anthropic")
    check(window.base_url_edit.text() == "https://api.anthropic.com/v1", "Claude 地址自动填入")
    check("console.anthropic.com" in window.console_label.text(), "控制台链接自动更新")

    select_provider(window, "lmstudio")
    check(window.base_url_edit.text() == "http://127.0.0.1:1234/v1", "LM Studio 本地地址自动填入")
    check(window.api_env_edit.text() == "", "本地厂商 Key 变量名清空")

    print("[2] 自定义厂商不清空已填地址")
    select_provider(window, "deepseek")
    manual = "https://my-own-endpoint/v1"
    window.base_url_edit.setText(manual)
    select_provider(window, "custom")
    check(window.base_url_edit.text() == manual, "切到自定义厂商时保留手填地址")

    print("[3] 按钮检查：无「应用厂商预设」，但保留重置按钮")
    texts = [b.text() for b in window.findChildren(QPushButton)]
    check("应用厂商预设" not in texts, "不存在「应用厂商预设」按钮")
    check(not any("应用厂商" in t for t in texts), "不存在任何「应用厂商」类按钮")
    check(
        any(t in ("重置", "重置为厂商默认") for t in texts),
        "存在「重置」按钮（恢复厂商默认地址）",
    )

    print("[5] 重置按钮恢复厂商默认地址")
    select_provider(window, "deepseek")
    window.base_url_edit.setText("https://乱改的地址/v1")
    window._on_reset_provider_defaults()
    check(window.base_url_edit.text() == "https://api.deepseek.com/v1", "重置后恢复 DeepSeek 默认地址")

    print("[6] 保存/重载往返：自定义地址不丢")
    window.base_url_edit.setText("https://my-proxy.example.com/v1")
    collected = window._collect_config()
    check(collected.llm.base_url == "https://my-proxy.example.com/v1", "收集到自定义地址")
    check(collected.llm.provider == "deepseek", "厂商 key 正确收集")
    check(collected.llm.api_style == "openai", "api_style 随厂商自动判定")

    window.close()
    app.quit()

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("全部通过：选厂商即自动应用，无多余步骤。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
