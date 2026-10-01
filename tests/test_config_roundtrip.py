"""配置的序列化/反序列化往返测试（GUI 保存配置的可靠性保障）。"""

from __future__ import annotations

import unittest

from wxbot.config import (
    AppConfig,
    ReplyConfig,
    ReplyRule,
    dump_config_text,
    parse_config_text,
)


class ConfigRoundtripTests(unittest.TestCase):
    def test_dump_then_parse(self):
        cfg = AppConfig()
        cfg.mode = "auto"
        cfg.whitelist.chats = ("张三", "家庭群")
        cfg.reply = ReplyConfig(
            engine="llm",
            rules=(ReplyRule(keywords=("在吗", "在么"), reply='在的，说"重点"～'),),
        )
        cfg.llm.base_url = "http://127.0.0.1:11434/v1"
        cfg.llm.model = "qwen3:8b"
        cfg.llm.api_key_env = ""
        cfg.skills.persona.description = '幽默，喜欢用"哈"和表情\n第二行也要保留'
        cfg.skills.learned.auto_after_replies = 12
        cfg.ui.theme = "light"
        cfg.ui.poll_interval_sec = 5.5

        text = dump_config_text(cfg)
        parsed = parse_config_text(text)

        self.assertEqual(parsed.mode, "auto")
        self.assertEqual(parsed.whitelist.chats, ("张三", "家庭群"))
        self.assertEqual(parsed.reply.engine, "llm")
        self.assertEqual(parsed.reply.rules[0].keywords, ("在吗", "在么"))
        self.assertEqual(parsed.reply.rules[0].reply, '在的，说"重点"～')
        self.assertEqual(parsed.llm.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(parsed.llm.model, "qwen3:8b")
        self.assertEqual(parsed.skills.persona.description, '幽默，喜欢用"哈"和表情\n第二行也要保留')
        self.assertTrue(parsed.skills.safety.enabled)
        self.assertTrue(parsed.skills.learned.enabled)
        self.assertEqual(parsed.skills.learned.auto_after_replies, 12)
        self.assertEqual(parsed.ui.theme, "light")
        self.assertEqual(parsed.ui.poll_interval_sec, 5.5)

    def test_default_appconfig_parses_own_dump(self):
        cfg = AppConfig()  # 默认 engine=rules，白名单为空
        parsed = parse_config_text(dump_config_text(cfg))
        self.assertEqual(parsed.mode, "dry_run")
        self.assertEqual(parsed.whitelist.chats, ())
        self.assertEqual(parsed.reply.engine, "rules")
        self.assertEqual(parsed.ui.theme, "dark", "默认主题应为深色")

    def test_invalid_theme_rejected(self):
        cfg = AppConfig()
        text = dump_config_text(cfg).replace('theme = "dark"', 'theme = "neon"')
        with self.assertRaises(Exception):
            parse_config_text(text)


if __name__ == "__main__":
    unittest.main()
