"""回复流水线单元测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wxbot.brain.learned import LearnedItem, LearnedStore
from wxbot.brain.llm import LLMError, LLMResult
from wxbot.brain.memory import ChatMemory
from wxbot.brain.pipeline import PipelineResult, ReplyPipeline
from wxbot.config import (
    AppConfig,
    GroupPolicySkillConfig,
    LLMConfig,
    ReplyConfig,
    ReplyRule,
    SafetyConfig,
    SkillsConfig,
    WhitelistConfig,
)
from wxbot.safety.gateway import SafetyGateway
from wxbot.wechat.base import IncomingMessage


def make_config(engine: str = "rules") -> AppConfig:
    return AppConfig(
        mode="auto",
        safety=SafetyConfig(
            quiet_hours=(),
            max_per_minute=10,
            max_per_hour=100,
            max_per_day=1000,
            min_reply_delay_sec=2.0,
            max_reply_delay_sec=6.0,
            auto_trip_on_failures=5,
        ),
        whitelist=WhitelistConfig(enabled=True, chats=("张三", "工作群")),
        reply=ReplyConfig(
            engine=engine,
            rules=(ReplyRule(keywords=("在吗",), reply="在的～"),),
        ),
        llm=LLMConfig(base_url="http://127.0.0.1:11434/v1", model="test-model"),
        skills=SkillsConfig(
            group_policy=GroupPolicySkillConfig(
                enabled=True, require_mention=True, extra_triggers=()
            )
        ),
    )


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.memory_path = self.tmp / "mem.json"

    def tearDown(self):
        self._tmp.cleanup()

    def make_pipeline(
        self,
        cfg: AppConfig,
        generator=None,
        store: LearnedStore | None = None,
    ):
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        memory = ChatMemory(self.memory_path)
        learned_store = store or LearnedStore(self.tmp / "learned.json")
        pipeline = ReplyPipeline(
            cfg, gateway, memory, generator=generator, learned_store=learned_store
        )
        return pipeline, memory

    # ---------- 规则引擎 ----------
    def test_rules_reply(self):
        cfg = make_config("rules")
        pipeline, memory = self.make_pipeline(cfg)
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="在吗？"))
        self.assertEqual(result.action, "replied")
        self.assertEqual(result.reply_text, "在的～")
        self.assertTrue(2.0 <= result.delay_sec <= 6.0)
        self.assertIn(("them", "在吗？"), memory.recent("张三", 3))

    def test_denied_by_whitelist(self):
        cfg = make_config("rules")
        pipeline, _ = self.make_pipeline(cfg)
        result = pipeline.handle(IncomingMessage(chat_name="陌生人", text="你好"))
        self.assertEqual(result.action, "denied")
        self.assertIn("白名单", result.reason)

    def test_skipped_when_no_rule_matches(self):
        cfg = make_config("rules")
        pipeline, _ = self.make_pipeline(cfg)
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="今天天气不错"))
        self.assertEqual(result.action, "skipped")

    def test_group_gate_blocks_without_trigger(self):
        cfg = make_config("rules")
        pipeline, _ = self.make_pipeline(cfg)
        result = pipeline.handle(
            IncomingMessage(chat_name="工作群", text="大家早", is_group=True)
        )
        self.assertEqual(result.action, "skipped")
        self.assertIn("群", result.reason)

    # ---------- LLM 引擎 ----------
    def test_llm_flow_uses_prompt_and_history(self):
        cfg = make_config("llm")
        captured: dict = {}

        def fake_generator(text, *, system_prompt, history):
            captured["text"] = text
            captured["system"] = system_prompt
            captured["history"] = history
            return "好呀～"

        pipeline, memory = self.make_pipeline(cfg, generator=fake_generator)
        memory.add("张三", "them", "周末去哪玩")
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="你想好了吗"))
        self.assertEqual(result.action, "replied")
        self.assertEqual(result.reply_text, "好呀～")
        self.assertEqual(captured["text"], "你想好了吗")
        self.assertIn("你正在代替微信主人回复", captured["system"])
        self.assertIn("不要说自己是 AI", captured["system"])
        self.assertIn("说话风格", captured["system"])
        self.assertIn(("user", "周末去哪玩"), captured["history"])

    def test_llm_error_handled(self):
        cfg = make_config("llm")

        def bad_generator(*args, **kwargs):
            raise LLMError("连接失败")

        pipeline, _ = self.make_pipeline(cfg, generator=bad_generator)
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="hi"))
        self.assertEqual(result.action, "error")
        self.assertIn("连接失败", result.reason)

    def test_safety_blocks_dangerous_reply(self):
        cfg = make_config("llm")
        cfg.skills.safety.banned_topics = ("验证码",)

        def risky_generator(*args, **kwargs):
            return "你把验证码发我一下"

        pipeline, _ = self.make_pipeline(cfg, generator=risky_generator)
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="在干嘛"))
        self.assertEqual(result.action, "skipped")
        self.assertIn("拦截", result.reason)

    # ---------- 记忆只在"真的处理了"时才写（v2.5.1 回归） ----------
    def test_failed_generation_does_not_pollute_memory(self):
        """生成失败绝不能把用户消息写进记忆。

        回归：早期版本在取完历史就写记忆，于是每次重试都塞一遍 ——
        重试 3 次后提示词里出现 4 条「你好」，越重试越长越乱。
        """
        cfg = make_config("llm")
        calls = {"n": 0}

        def flaky_generator(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise LLMError("timed out")
            return "在的～"

        pipeline, memory = self.make_pipeline(cfg, generator=flaky_generator)
        for _ in range(2):
            result = pipeline.handle(IncomingMessage(chat_name="张三", text="你好"))
            self.assertEqual(result.action, "error")

        self.assertEqual(
            memory.recent("张三", 10), [], "两次失败后记忆里不该有任何东西"
        )

        result = pipeline.handle(IncomingMessage(chat_name="张三", text="你好"))
        self.assertEqual(result.action, "replied")
        self.assertEqual(
            [text for _role, text in memory.recent("张三", 10)],
            ["你好"],
            "成功那一次才记一条，且只记一条",
        )

    def test_blocked_reply_does_not_pollute_memory(self):
        """被安全技能拦下的回复，同样不该留下记忆。"""
        cfg = make_config("llm")
        cfg.skills.safety.banned_topics = ("验证码",)

        def risky_generator(*args, **kwargs):
            return "把验证码发我"

        pipeline, memory = self.make_pipeline(cfg, generator=risky_generator)
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="在干嘛"))
        self.assertEqual(result.action, "skipped")
        self.assertEqual(memory.recent("张三", 10), [])

    def test_denied_message_not_recorded(self):
        """白名单拦截的消息不该进记忆。"""
        cfg = make_config("llm")
        pipeline, memory = self.make_pipeline(cfg, generator=lambda *a, **k: "在的")
        result = pipeline.handle(IncomingMessage(chat_name="陌生人", text="在吗"))
        self.assertEqual(result.action, "denied")
        self.assertEqual(memory.recent("陌生人", 10), [])

    # ---------- 观测数据：上下文占用 + 思考过程（v2.6.0） ----------
    def test_pipeline_exposes_context_usage_and_reasoning(self):
        """「运行」页要显示上下文窗口占用和思考过程，数据必须从流水线透出来。"""
        cfg = make_config("llm")

        def generator(text, *, system_prompt, history):
            return LLMResult(
                text="在的～",
                reasoning="Thinking Process: 先看人设，再看上下文……",
                prompt_tokens=1203,
                completion_tokens=17,
                context_length=8192,
                finish_reason="stop",
            )

        pipeline, _ = self.make_pipeline(cfg, generator=generator)
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="在吗"))
        self.assertEqual(result.action, "replied")
        self.assertEqual(result.prompt_tokens, 1203)
        self.assertEqual(result.context_length, 8192)
        self.assertAlmostEqual(result.context_ratio, 1203 / 8192, places=4)
        self.assertIn("1,203", result.context_display)
        self.assertIn("15%", result.context_display)
        self.assertIn("Thinking Process", result.reasoning)

    def test_string_generator_still_works(self):
        """测试注入的生成器返回纯字符串时不能崩（向后兼容）。"""
        cfg = make_config("llm")
        pipeline, _ = self.make_pipeline(
            cfg, generator=lambda text, *, system_prompt, history: "好的～"
        )
        result = pipeline.handle(IncomingMessage(chat_name="张三", text="在吗"))
        self.assertEqual(result.action, "replied")
        self.assertEqual(result.reply_text, "好的～")
        self.assertEqual(result.context_ratio, 0.0)
        self.assertEqual(result.context_display, "—")

    # ---------- 自学习技能 ----------
    def test_learned_prompt_injection(self):
        cfg = make_config("llm")
        captured: dict = {}

        def fake_generator(text, *, system_prompt, history):
            captured["system"] = system_prompt
            return "好的"

        store = LearnedStore(self.tmp / "learned.json")
        store.add(LearnedItem.create("style", "global", "风格", "爱用哈哈哈"))
        store.add(LearnedItem.create("note", "张三", "备注", "张三是我同事，聊工作为主"))
        store.add(
            LearnedItem.create(
                "faq", "global", "加班", "别人问加班就说到家再说", keywords=("加班",)
            )
        )
        pipeline, _ = self.make_pipeline(cfg, generator=fake_generator, store=store)

        pipeline.handle(IncomingMessage(chat_name="张三", text="今天要加班吗"))
        system = captured["system"]
        self.assertIn("爱用哈哈哈", system)
        self.assertIn("张三是我同事", system)
        self.assertIn("到家再说", system)

        # 关键词未命中：faq 参考不注入；风格仍注入
        pipeline.handle(IncomingMessage(chat_name="张三", text="中午吃什么"))
        self.assertNotIn("到家再说", captured["system"])
        self.assertIn("爱用哈哈哈", captured["system"])

        # 会话备注只对指定会话生效
        pipeline.handle(IncomingMessage(chat_name="工作群", text="今天发版吗"))
        self.assertNotIn("张三是我同事", captured["system"])

    def test_learned_disabled_item_not_used(self):
        cfg = make_config("llm")
        captured: dict = {}

        def fake_generator(text, *, system_prompt, history):
            captured["system"] = system_prompt
            return "好的"

        store = LearnedStore(self.tmp / "learned.json")
        item = LearnedItem.create("style", "global", "风格", "很正式的书面语")
        item.enabled = False
        store.add(item)
        pipeline, _ = self.make_pipeline(cfg, generator=fake_generator, store=store)
        pipeline.handle(IncomingMessage(chat_name="张三", text="在吗"))
        self.assertNotIn("很正式的书面语", captured["system"])

    def test_auto_learn_due_counter(self):
        cfg = make_config("rules")
        cfg.skills.learned.auto_after_replies = 2
        pipeline, _ = self.make_pipeline(cfg)
        msg = IncomingMessage(chat_name="张三", text="在吗")
        result = PipelineResult("replied", "ok", "在的～", 0.0)
        pipeline.note_sent(msg, result)
        self.assertFalse(pipeline.consume_learn_due())
        pipeline.note_sent(msg, result)
        self.assertTrue(pipeline.consume_learn_due())
        self.assertFalse(pipeline.consume_learn_due())


if __name__ == "__main__":
    unittest.main()
