"""技能系统：让 AI 回复更聪明、更安全。

每个技能提供三类能力（按需实现）：
1) gate(ctx)            —— 消息级放行/拦截（例：群聊没有触发词就不回）
2) prompt(ctx)          —— 给系统提示词注入一段（人设、安全规则……）
3) check_reply(ctx, r)  —— 对生成的回复做最后审查（命中违禁内容则拒绝发送）

新增技能：继承 Skill 实现上述方法，并在 SkillRegistry 中注册。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import (
    GroupPolicySkillConfig,
    PersonaSkillConfig,
    SafetySkillConfig,
    SkillsConfig,
)
from .learned import LearnedStore


@dataclass
class ReplyContext:
    chat_name: str
    incoming_text: str
    is_group: bool = False
    history: tuple[tuple[str, str], ...] = ()


@dataclass
class SkillOutcome:
    allow: bool = True
    reason: str = ""


class Skill:
    name = "skill"

    def gate(self, ctx: ReplyContext) -> SkillOutcome:
        return SkillOutcome()

    def prompt(self, ctx: ReplyContext) -> str | None:
        return None

    def check_reply(self, ctx: ReplyContext, reply: str) -> SkillOutcome:
        return SkillOutcome()


def build_persona_prompt(config: PersonaSkillConfig) -> str:
    """把「人设」配置拼成给模型的指令。空字段自动省略。

    图形界面「人设」页的实时预览也用这个函数，保证"看到的 = AI 实际收到的"。
    """
    from ..config import EMOJI_LABELS, LENGTH_LABELS, TONE_LABELS

    lines: list[str] = []

    identity = (config.identity or "").strip()
    if identity:
        # 用户常直接写「我是 XXX」；拼进"你扮演的身份"会很别扭，这里去掉主语
        cleaned = re.sub(r"^\s*(?:我是|我叫|本人是)\s*", "", identity).strip(" 。.")
        if cleaned:
            lines.append(f"- 你的身份：{cleaned}")
            lines.append(
                f"- 对方问「你是谁」「你是机器人吗」时，就回答：我是{cleaned}。（只说这句，别解释）"
            )

    description = (config.description or "").strip()
    if description:
        lines.append(f"- 说话风格：{description}")

    tone = TONE_LABELS.get(config.tone, "")
    if config.tone != "auto" and tone:
        lines.append(f"- 语气：{tone}")

    if config.formality <= 30:
        lines.append("- 正式程度：很随意，像朋友聊天，不要说场面话")
    elif config.formality >= 70:
        lines.append("- 正式程度：比较正式，用词得体、讲礼貌")
    else:
        lines.append("- 正式程度：介于随意与正式之间")

    length_label = LENGTH_LABELS.get(config.length, "")
    if length_label:
        lines.append(f"- 回复长度：{length_label}")

    emoji_label = EMOJI_LABELS.get(config.emoji, "")
    if emoji_label:
        lines.append(f"- 表情符号：{emoji_label}")

    catchphrases = [c.strip() for c in config.catchphrases if c.strip()]
    if catchphrases:
        lines.append("- 可以用这些口头禅（自然融入，别硬塞）：" + "、".join(catchphrases))

    avoid = [a.strip() for a in config.avoid if a.strip()]
    if avoid:
        lines.append("- 绝对不要：" + "、".join(avoid))

    if not lines:
        return ""
    return "关于我的人设（务必按这个来）：\n" + "\n".join(lines)


# 硬性规则：**永远追加在系统提示词的最后**，用户改不动。
# 为什么单独放这里：早期把它写进"默认系统提示词"，结果用户一自定义就容易
# 出现「你是代回复助手，但不要暴露身份」这种自相矛盾的写法，模型就会自曝身份。
# 放在最后、且措辞是"即使前面这么说过也不采纳"，冲突时以本段为准。
MANDATORY_RULES = (
    "\n\n【硬性规则（优先级最高，前面有冲突的说法以本段为准）】\n"
    "1. 绝对不能说自己是 AI、机器人、助手、程序、模型、人工智能或「代回复」，"
    "哪怕前面的设定里这样写过，也一律不采纳；\n"
    "2. 对方问「你是谁」「你叫什么」「你是机器人吗」「你是不是 AI」时，"
    "只回答上面「你的身份」那一句话，不要解释、不要承认任何程序身份；\n"
    "3. 只回应当前这一条消息，不要编造没发生过的事；\n"
    "4. 回复要短，像本人随手打的字。"
)


class PersonaSkill(Skill):
    """人设模仿：把「我是谁、怎么说话」注入系统提示词。"""

    name = "persona"

    def __init__(self, config: PersonaSkillConfig):
        self._config = config

    def prompt(self, ctx: ReplyContext) -> str | None:
        return build_persona_prompt(self._config) or None


class SafetySkill(Skill):
    """安全护栏：敏感话题 + 不替本人做承诺；并对生成的回复做违禁词审查。"""

    name = "safety"

    def __init__(self, config: SafetySkillConfig):
        self._config = config

    def prompt(self, ctx: ReplyContext) -> str | None:
        notes: list[str] = []
        topics = [t.strip() for t in self._config.banned_topics if t.strip()]
        if topics:
            notes.append(
                "不要主动谈论以下话题，也不要答应对方与之相关的任何请求："
                + "、".join(topics)
                + "。"
            )
        if self._config.commitment_guard:
            notes.append(
                "不要替我做任何承诺（不答应具体时间、不答应办事、不确认金额）；"
                "拿不准就回复「我等下看下」。"
            )
        if not notes:
            return None
        return "安全规则：" + " ".join(notes)

    def check_reply(self, ctx: ReplyContext, reply: str) -> SkillOutcome:
        for topic in self._config.banned_topics:
            topic = topic.strip()
            if topic and topic in reply:
                return SkillOutcome(allow=False, reason=f"回复命中违禁话题「{topic}」")
        return SkillOutcome()


class GroupPolicySkill(Skill):
    """群聊策略：默认只有包含触发词（默认为 @我）的群消息才回复。"""

    name = "group_policy"

    def __init__(self, config: GroupPolicySkillConfig):
        self._config = config

    def gate(self, ctx: ReplyContext) -> SkillOutcome:
        if not ctx.is_group or not self._config.require_mention:
            return SkillOutcome()
        triggers = ["@我"] + [t.strip() for t in self._config.extra_triggers if t.strip()]
        if any(t and t in ctx.incoming_text for t in triggers):
            return SkillOutcome()
        return SkillOutcome(allow=False, reason="群聊消息未包含触发词（默认要求 @我）")


class LearnedSkill(Skill):
    """自学习技能：使用「技能库」里启用中的条目。

    - style：全局风格补充
    - note：只对指定会话生效的背景信息
    - faq：按关键词命中时给出的回复习惯参考（只作提示，不直接照发）
    """

    name = "learned"

    def __init__(self, store: LearnedStore):
        self._store = store

    def prompt(self, ctx: ReplyContext) -> str | None:
        parts: list[str] = []
        for item in self._store.items(enabled_only=True):
            if len(parts) >= 8:
                break
            if item.type == "style":
                parts.append(f"风格补充：{item.content}")
            elif item.type == "note":
                if item.scope == ctx.chat_name:
                    parts.append(f"关于「{ctx.chat_name}」的背景信息：{item.content}")
            elif item.type == "faq":
                if item.scope not in ("global", ctx.chat_name):
                    continue
                if item.keywords and not any(
                    k in ctx.incoming_text for k in item.keywords
                ):
                    continue
                parts.append(f"类似消息的回复习惯（参考，不要照抄）：{item.content}")
        if not parts:
            return None
        return "\n".join(parts)


class SkillRegistry:
    def __init__(self, config: SkillsConfig, learned_store: LearnedStore | None = None):
        self._config = config
        self.memory = config.memory
        self._skills: list[Skill] = []
        if config.persona.enabled:
            self._skills.append(PersonaSkill(config.persona))
        if config.safety.enabled:
            self._skills.append(SafetySkill(config.safety))
        if config.group_policy.enabled:
            self._skills.append(GroupPolicySkill(config.group_policy))
        if config.learned.enabled:
            self._skills.append(LearnedSkill(learned_store or LearnedStore()))

    @property
    def active_names(self) -> list[str]:
        return [skill.name for skill in self._skills]

    def gate(self, ctx: ReplyContext) -> SkillOutcome:
        for skill in self._skills:
            outcome = skill.gate(ctx)
            if not outcome.allow:
                return outcome
        return SkillOutcome()

    def build_system_prompt(self, ctx: ReplyContext, base_prompt: str) -> str:
        fragments = [base_prompt.strip()]
        for skill in self._skills:
            fragment = skill.prompt(ctx)
            if fragment:
                fragments.append(fragment)
        # 硬性规则永远在最后 —— 即使前面的自定义提示词写了自相矛盾的话，也以它为准
        fragments.append(MANDATORY_RULES)
        return "\n".join(f for f in fragments if f)

    def check_reply(self, ctx: ReplyContext, reply: str) -> SkillOutcome:
        for skill in self._skills:
            outcome = skill.check_reply(ctx, reply)
            if not outcome.allow:
                return outcome
        return SkillOutcome()
