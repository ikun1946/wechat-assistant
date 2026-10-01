"""技能自学习：让 AI 复盘最近的聊天记录，把重复出现的信息整理成技能条目。

流程：聊天记录（ChatMemory 里的 them/me 消息）→ 模型整理 → LearnedStore（逐条可开关）。
本模块只产出条目，不参与发送；条目如何生效见 skills.LearnedSkill。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .learned import LearnedItem, LearnedStore

LEARN_SYSTEM_PROMPT = (
    "你是微信自动回复系统的「技能整理员」。用户会给你若干段聊天记录"
    "（标注为「对方」的是消息来源，「我」是微信主人本人的回复）。\n"
    "请从中总结出能帮助系统以后更好替本人回复的「技能条目」，"
    "只输出一个严格的 JSON 数组，不要输出任何其它文字。\n"
    "每个条目的字段：\n"
    '- type: "faq" | "note" | "style"\n'
    '- scope: "global"，或具体会话名（仅 note 用会话名）\n'
    "- keywords: 字符串数组，仅 faq 需要（触发参考的关键词）\n"
    "- title: 一句话摘要（不超过 20 字）\n"
    "- content: 给 AI 的指导（简洁、可执行，不超过 50 字）\n"
    "- examples: 字符串数组，最多 2 条原文片段作为依据\n"
    "整理要求：\n"
    "1) 只总结有重复出现或明确有价值的信息；没有值得总结的就输出 []；\n"
    "2) faq 要总结「对方说什么 → 本人一般怎么回」的规律，而不是照抄单次回复；\n"
    "3) note 描述某个会话的背景（对方是谁、聊什么、注意什么）；\n"
    "4) style 描述本人一贯的说话风格与口头禅；\n"
    "5) 最多 8 条；不确定的宁可不输出。"
)


class LearnError(Exception):
    """学习过程失败（模型输出无法解析等）。"""


@dataclass
class ConversationSample:
    chat_name: str
    messages: tuple[tuple[str, str], ...]  # (them|me, text)


@dataclass
class LearnReport:
    added: int = 0
    duplicates: int = 0
    invalid: int = 0
    total: int = 0


Generator = Callable[..., str]


class SkillLearner:
    def __init__(
        self, store: LearnedStore, generator: Generator, *, max_items_per_run: int = 8
    ):
        self._store = store
        self._generator = generator
        self._max_items = max(1, int(max_items_per_run))

    # ---------- 对外 ----------
    def learn_from(self, samples: list[ConversationSample]) -> LearnReport:
        usable = [s for s in samples if len(s.messages) >= 2]
        if not usable:
            raise LearnError("没有足够的聊天记录（每条会话至少需要 2 条消息）")

        prompt = self._build_prompt(usable)
        output = self._generator(prompt, system_prompt=LEARN_SYSTEM_PROMPT, history=[])
        raw_items = _extract_json_array(str(output))

        report = LearnReport()
        for raw in raw_items[:50]:
            if report.added >= self._max_items:
                break
            item = _parse_item(raw)
            if item is None:
                report.invalid += 1
                continue
            if self._store.add(item):
                report.added += 1
            else:
                report.duplicates += 1
        report.total = len(self._store)
        return report

    # ---------- 内部 ----------
    def _build_prompt(self, samples: list[ConversationSample]) -> str:
        blocks: list[str] = []
        for sample in samples:
            lines = [f"【会话：{sample.chat_name}】"]
            for role, text in sample.messages:
                speaker = "对方" if role == "them" else "我"
                lines.append(f"{speaker}: {text}")
            block = "\n".join(lines)
            if len(block) > 3000:  # 单会话过长时保留最近部分
                block = block[-3000:]
            blocks.append(block)
        body = "\n\n".join(blocks)
        if len(body) > 9000:  # 总量兜底
            body = body[-9000:]
        return "以下是最近的聊天记录，请整理技能条目：\n\n" + body


# ---------------------------------------------------------------------------
# 解析工具（模型输出 → 结构化条目）
# ---------------------------------------------------------------------------

def _extract_json_array(text: str) -> list:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise LearnError("模型输出里没有找到 JSON 数组")
    try:
        data = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LearnError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, list):
        raise LearnError("模型输出不是数组")
    return data


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _parse_item(raw: object) -> LearnedItem | None:
    if not isinstance(raw, dict):
        return None
    item_type = _clean(raw.get("type", ""), 10).lower()
    if item_type not in ("faq", "note", "style"):
        return None
    scope = _clean(raw.get("scope", "global"), 40) or "global"
    if item_type == "style":
        scope = "global"  # 风格补充一律全局生效
    content = _clean(raw.get("content", ""), 200)
    if not content:
        return None
    title = _clean(raw.get("title", ""), 60) or content[:30]
    keywords = tuple(
        _clean(k, 20) for k in (raw.get("keywords") or []) if _clean(k, 20)
    )[:8]
    examples = tuple(
        _clean(e, 120) for e in (raw.get("examples") or []) if _clean(e, 120)
    )[:2]
    return LearnedItem.create(
        type=item_type, scope=scope, title=title, content=content,
        keywords=keywords, examples=examples,
    )
