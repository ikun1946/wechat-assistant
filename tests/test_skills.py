"""技能系统单元测试。"""

from __future__ import annotations

import unittest

from wxbot.brain.skills import (
    GroupPolicySkill,
    ReplyContext,
    SafetySkill,
    SkillRegistry,
)
from wxbot.config import (
    GroupPolicySkillConfig,
    PersonaSkillConfig,
    SafetySkillConfig,
    SkillsConfig,
)


def ctx(text: str, *, group: bool = False) -> ReplyContext:
    return ReplyContext(chat_name="测试会话", incoming_text=text, is_group=group)


class GroupPolicyTests(unittest.TestCase):
    def make_skill(self, triggers=("小马",)) -> GroupPolicySkill:
        return GroupPolicySkill(
            GroupPolicySkillConfig(enabled=True, require_mention=True, extra_triggers=triggers)
        )

    def test_group_without_mention_blocked(self):
        outcome = self.make_skill().gate(ctx("大家早上好", group=True))
        self.assertFalse(outcome.allow)

    def test_group_with_extra_trigger_allowed(self):
        outcome = self.make_skill().gate(ctx("@小马 帮我看下这个", group=True))
        self.assertTrue(outcome.allow)

    def test_group_with_default_mention_allowed(self):
        outcome = self.make_skill().gate(ctx("@我 在吗", group=True))
        self.assertTrue(outcome.allow)

    def test_private_chat_unaffected(self):
        outcome = self.make_skill().gate(ctx("在吗", group=False))
        self.assertTrue(outcome.allow)


class SafetySkillTests(unittest.TestCase):
    def test_prompt_mentions_banned_topics_and_commitment(self):
        skill = SafetySkill(
            SafetySkillConfig(enabled=True, banned_topics=("验证码",), commitment_guard=True)
        )
        text = skill.prompt(ctx("你好")) or ""
        self.assertIn("验证码", text)
        self.assertIn("承诺", text)

    def test_check_reply_blocks_banned_topic(self):
        skill = SafetySkill(
            SafetySkillConfig(enabled=True, banned_topics=("验证码",), commitment_guard=True)
        )
        outcome = skill.check_reply(ctx("在吗"), "你把验证码发我一下")
        self.assertFalse(outcome.allow)

    def test_check_reply_allows_normal_text(self):
        skill = SafetySkill(
            SafetySkillConfig(enabled=True, banned_topics=("验证码",), commitment_guard=True)
        )
        outcome = skill.check_reply(ctx("在吗"), "在的，稍后回你～")
        self.assertTrue(outcome.allow)


class PromptAssemblyTests(unittest.TestCase):
    def make_registry(self) -> SkillRegistry:
        return SkillRegistry(
            SkillsConfig(
                persona=PersonaSkillConfig(
                    enabled=True, description="幽默、爱用表情、偶尔用「哈哈哈」"
                ),
                safety=SafetySkillConfig(enabled=True),
                group_policy=GroupPolicySkillConfig(enabled=True),
            )
        )

    def test_prompt_contains_base_persona_and_safety(self):
        prompt = self.make_registry().build_system_prompt(ctx("hi"), "基础提示词")
        self.assertIn("基础提示词", prompt)
        self.assertIn("说话风格", prompt)
        self.assertIn("安全规则", prompt)

    def test_gate_blocks_group_without_trigger(self):
        outcome = self.make_registry().gate(ctx("大家早", group=True))
        self.assertFalse(outcome.allow)

    def test_gate_allows_private_chat(self):
        outcome = self.make_registry().gate(ctx("早", group=False))
        self.assertTrue(outcome.allow)


if __name__ == "__main__":
    unittest.main()
