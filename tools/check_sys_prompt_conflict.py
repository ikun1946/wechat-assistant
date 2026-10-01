"""自检：「系统提示词」与人设的冲突防护。

用法：.venv/Scripts/python.exe tools/check_sys_prompt_conflict.py

检查项：
1) 实际 config.toml 里的 system_prompt 已清空（不再与「人设」自相矛盾）；
2) 系统提示词默认折叠在「高级设置」里，不干扰日常使用；
3) 填入含「助手/AI/代回复」等字眼时，立刻弹出冲突警告；
4) 清空后警告消失；
5) 最终注入模型的完整系统提示词 = 默认提示词 + 人设 + 末尾硬性规则，
   且硬性规则永远排在最后（人改不动）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

import wxbot.gui as gui  # noqa: E402
from wxbot.config import load_config  # noqa: E402

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  ✅ " if condition else "  ❌ ") + label)
    if not condition:
        failures.append(label)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    print("[1] 磁盘上的 config.toml")
    cfg = load_config()
    check(cfg.llm.system_prompt.strip() == "", "system_prompt 已清空（留空=用内置提示词+人设）")
    check(bool(cfg.skills.persona.identity.strip()), f"人设身份仍然保留：{cfg.skills.persona.identity[:20]}…")

    print("[2] 界面加载状态")
    window = gui.MainWindow()
    check(window.sys_prompt_edit.toPlainText().strip() == "", "界面里的系统提示词框是空的")
    check(not window.sys_prompt_warn.isVisible(), "空内容时不显示警告")
    # 高级区默认折叠：编辑框虽然存在，但不属于可见的常规区域
    check(
        window.sys_prompt_edit.isVisibleTo(window) is False,
        "系统提示词默认折叠隐藏（不干扰日常使用）",
    )

    print("[3] 填入矛盾内容 → 立刻警告")
    window.sys_prompt_edit.setPlainText("你是微信代回复助手，是一个 AI。")
    app.processEvents()
    warn_text = window.sys_prompt_warn.text()
    # 高级区默认折叠，父级不可见，所以看 isHidden()（自身显隐标记）而不是 isVisible()
    check(not window.sys_prompt_warn.isHidden(), "警告条被标记为显示")
    check("⚠️" in warn_text, "警告文案带警示符号")
    check("代回复" in warn_text and "AI" in warn_text, f"点出了具体风险词：{warn_text[:40]}…")

    print("[4] 清空 → 警告消失")
    window.sys_prompt_edit.setPlainText("")
    app.processEvents()
    check(window.sys_prompt_warn.isHidden(), "警告条恢复隐藏")

    print("[5] 最终注入模型的系统提示词")
    from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT
    from wxbot.brain.skills import MANDATORY_RULES, ReplyContext, SkillRegistry

    base = cfg.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
    check("代回复助手" not in base, "默认提示词自称的不是「代回复助手」")
    registry = SkillRegistry(cfg.skills)
    full = registry.build_system_prompt(ReplyContext("测试", "在吗"), base)
    check("你的身份：" in full, "人设身份已注入（写成「你的身份：…」）")
    # 标准答案必须由**当前配置**推导，不能写死具体人名 ——
    # 否则换个人设这个自检就误报，而且会把本机身份带进仓库。
    import re as _re

    cleaned = _re.sub(
        r"^\s*(?:我是|我叫|本人是)\s*", "", cfg.skills.persona.identity
    ).strip(" 。.")
    check(
        cleaned and f"我是{cleaned}" in full,
        "被问「你是谁」时的标准答案已就位（按当前人设推导）",
    )
    check(full.rstrip().endswith(MANDATORY_RULES.strip()), "硬性规则永远排在最后（用户改不动）")
    check(
        full.index("优先级最高") > full.index("你的身份"),
        "硬性规则在人设之后，冲突时以它为准",
    )
    check("一律不采纳" in full, "硬性规则能压过前面的自相矛盾设定")

    window.close()
    app.quit()

    print()
    if failures:
        print(f"共 {len(failures)} 项未通过：")
        for item in failures:
            print("  - " + item)
        return 1
    print("全部通过：系统提示词已无害化 + 冲突可被实时发现。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
