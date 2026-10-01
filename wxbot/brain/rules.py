"""规则回复引擎：关键词 → 固定回复。

最简单也最可控，先跑通它，确认整条链路正常后再考虑启用 LLM。
"""

from __future__ import annotations

from ..config import ReplyConfig


class RuleEngine:
    def __init__(self, config: ReplyConfig):
        self._config = config

    def generate(self, text: str) -> str | None:
        """返回回复文本；无命中返回 None（表示这条消息不该被回复）。"""
        for rule in self._config.rules:
            if any(keyword in text for keyword in rule.keywords):
                return rule.reply
        if self._config.default_enabled and self._config.default_text:
            return self._config.default_text
        return None
