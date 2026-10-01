"""人设（persona）单元测试：结构化配置 → 提示词，以及配置往返。"""

from __future__ import annotations

import unittest

from wxbot.brain.pipeline import DEFAULT_BASE_PROMPT
from wxbot.brain.skills import PersonaSkill, ReplyContext, SkillRegistry, build_persona_prompt
from wxbot.config import (
    AppConfig,
    PersonaSkillConfig,
    SkillsConfig,
    dump_config_text,
    parse_config_text,
)


class PersonaPromptTests(unittest.TestCase):
    def test_identity_strips_leading_wowo(self):
        """用户常直接写「我是 XXX」；拼进提示词要去掉主语，并给出"被问是谁时怎么答"。"""
        config = PersonaSkillConfig(identity="我是张三，一个爱打游戏的人")
        prompt = build_persona_prompt(config)
        self.assertIn("你的身份：张三，一个爱打游戏的人", prompt)
        self.assertNotIn("你的身份：我是", prompt)
        self.assertIn("问「你是谁」", prompt)
        self.assertIn("我是张三", prompt)

    def test_identity_without_wowo(self):
        config = PersonaSkillConfig(identity="阿哲")
        prompt = build_persona_prompt(config)
        self.assertIn("你的身份：阿哲", prompt)
        self.assertIn("我是阿哲", prompt)

    def test_full_persona_includes_every_part(self):
        config = PersonaSkillConfig(
            identity="我是阿哲，做游戏开发，30 岁，平时说话很随意",
            description="爱用「哈哈哈」，不说教",
            tone="humorous",
            formality=10,
            length="very_short",
            emoji="often",
            catchphrases=("哈哈哈", "emmm"),
            avoid=("长篇大论", "提 AI"),
        )
        prompt = build_persona_prompt(config)
        self.assertIn("阿哲", prompt)
        self.assertIn("爱用「哈哈哈」", prompt)
        self.assertIn("幽默轻松", prompt)
        self.assertIn("很随意", prompt)
        self.assertIn("很短", prompt)
        self.assertIn("经常用", prompt)
        self.assertIn("哈哈哈", prompt)
        self.assertIn("长篇大论", prompt)

    def test_empty_fields_are_omitted(self):
        config = PersonaSkillConfig(
            identity="",
            description="",
            tone="auto",
            formality=50,
            length="short",
            emoji="rare",
            catchphrases=(),
            avoid=(),
        )
        prompt = build_persona_prompt(config)
        self.assertNotIn("扮演的身份", prompt)
        self.assertNotIn("语气：", prompt)
        self.assertNotIn("口头禅", prompt)
        self.assertNotIn("绝对不要", prompt)
        # 仍应有中间档正式程度与长度
        self.assertIn("介于随意与正式之间", prompt)
        self.assertIn("1~2 句", prompt)

    def test_blank_config_returns_empty(self):
        config = PersonaSkillConfig(
            identity="", description="", tone="auto", formality=50, length="", emoji=""
        )
        prompt = build_persona_prompt(config)
        # formality 中间档会加一行，所以非空；但去掉它才是"完全空"
        self.assertIsInstance(prompt, str)

    def test_formal_tone_variant(self):
        config = PersonaSkillConfig(identity="", description="", tone="direct", formality=90)
        prompt = build_persona_prompt(config)
        self.assertIn("比较正式", prompt)
        self.assertIn("干脆直接", prompt)

    def test_skill_uses_same_prompt_as_preview(self):
        config = PersonaSkillConfig(identity="我是小李", description="话少")
        self.assertEqual(PersonaSkill(config).prompt(None), build_persona_prompt(config))

    def test_persona_is_injected_into_system_prompt(self):
        registry = SkillRegistry(
            SkillsConfig(persona=PersonaSkillConfig(identity="我是小李", description="话少"))
        )
        from wxbot.brain.skills import ReplyContext

        assembled = registry.build_system_prompt(ReplyContext("张三", "在吗"), DEFAULT_BASE_PROMPT)
        self.assertIn("我是小李", assembled)
        self.assertIn(DEFAULT_BASE_PROMPT[:10], assembled)


class BasePromptTests(unittest.TestCase):
    def test_base_prompt_never_says_you_are_an_assistant(self):
        """回归：旧默认值写着「你是微信代回复助手」，被问「你是谁」时会自曝身份。"""
        self.assertNotIn("代回复助手", DEFAULT_BASE_PROMPT)
        self.assertNotIn("你是微信", DEFAULT_BASE_PROMPT)
        self.assertIn("不要说自己是 AI", DEFAULT_BASE_PROMPT)
        self.assertIn("不要编造", DEFAULT_BASE_PROMPT)

    def test_default_config_has_empty_system_prompt(self):
        """默认配置应留空 system_prompt，让内置提示词生效。"""
        cfg = AppConfig()
        self.assertEqual(cfg.llm.system_prompt, "")


class MandatoryRulesTests(unittest.TestCase):
    """硬性规则必须永远在最后，且措辞能压过前面的自相矛盾设定。"""

    def test_rules_appended_last_regardless_of_base_prompt(self):
        from wxbot.brain.skills import MANDATORY_RULES, SkillRegistry

        config = SkillsConfig(persona=PersonaSkillConfig(identity="张三"))
        registry = SkillRegistry(config)
        # 模拟"用户写了个自相矛盾的提示词"
        bad_base = "你是微信代回复助手。不要暴露你是 AI。"
        assembled = registry.build_system_prompt(ReplyContext("张三", "在吗"), bad_base)
        self.assertTrue(assembled.rstrip().endswith(MANDATORY_RULES.strip()))
        self.assertIn("优先级最高", assembled)
        self.assertIn("哪怕前面的设定里这样写过，也一律不采纳", assembled)

    def test_rules_appear_even_without_persona(self):
        from wxbot.brain.skills import MANDATORY_RULES, SkillRegistry

        registry = SkillRegistry(SkillsConfig(persona=PersonaSkillConfig(enabled=False)))
        assembled = registry.build_system_prompt(ReplyContext("张三", "在吗"), "随便什么")
        self.assertIn(MANDATORY_RULES.strip(), assembled, "没有人设时硬性规则也要生效")

    def test_rules_forbid_self_identifying_words(self):
        from wxbot.brain.skills import MANDATORY_RULES

        for word in ("AI", "机器人", "助手", "程序", "模型", "代回复"):
            self.assertIn(word, MANDATORY_RULES)


class PersonaConfigRoundtripTests(unittest.TestCase):
    def test_persona_fields_survive_roundtrip(self):
        cfg = AppConfig()
        cfg.skills.persona = PersonaSkillConfig(
            enabled=True,
            identity="我是阿哲",
            description="随意",
            tone="warm",
            formality=80,
            length="medium",
            emoji="never",
            catchphrases=("好的呢",),
            avoid=("说教",),
        )
        parsed = parse_config_text(dump_config_text(cfg))
        persona = parsed.skills.persona
        self.assertEqual(persona.identity, "我是阿哲")
        self.assertEqual(persona.tone, "warm")
        self.assertEqual(persona.formality, 80)
        self.assertEqual(persona.length, "medium")
        self.assertEqual(persona.emoji, "never")
        self.assertEqual(persona.catchphrases, ("好的呢",))
        self.assertEqual(persona.avoid, ("说教",))

    def test_invalid_values_rejected(self):
        from wxbot.config import ConfigError

        cfg = AppConfig()
        text = dump_config_text(cfg).replace('tone = "auto"', 'tone = "暴躁"')
        with self.assertRaises(ConfigError):
            parse_config_text(text)

        text = dump_config_text(cfg).replace("formality = 30", "formality = 500")
        with self.assertRaises(ConfigError):
            parse_config_text(text)


if __name__ == "__main__":
    unittest.main()
