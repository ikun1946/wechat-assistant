"""运行控制器（Runner）单元测试：开关语义、统计、安全网关串联。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wxbot.brain.memory import ChatMemory
from wxbot.brain.pipeline import ReplyPipeline
from wxbot.config import (
    AppConfig,
    LLMConfig,
    ReplyConfig,
    ReplyRule,
    SafetyConfig,
    WhitelistConfig,
)
from wxbot.journal import Journal
from wxbot.runner import Runner, RunnerEvent
from wxbot.safety.gateway import SafetyGateway
from wxbot.wechat.base import IncomingMessage, WeChatClient


class FakeClient(WeChatClient):
    """可编排的假客户端：给定若干批消息，按次返回。"""

    def __init__(self, batches: list[list[IncomingMessage]], *, can_send: bool = True):
        self._batches = list(batches)
        self._index = 0
        self._can_send = can_send
        self.sent: list[tuple[str, str]] = []
        self.available = True

    @property
    def can_send(self) -> bool:
        return self._can_send

    def is_available(self) -> tuple[bool, str]:
        return (True, "ok") if self.available else (False, "微信窗口不可用")

    def poll_new_messages(self) -> list[IncomingMessage]:
        if self._index >= len(self._batches):
            return []
        batch = self._batches[self._index]
        self._index += 1
        return batch

    def send_text(self, chat_name: str, text: str) -> bool:
        if not self._can_send:
            return False
        self.sent.append((chat_name, text))
        return True


def make_config(mode: str = "dry_run", *, whitelist=("张三",)) -> AppConfig:
    return AppConfig(
        mode=mode,
        safety=SafetyConfig(
            quiet_hours=(),
            max_per_minute=10,
            max_per_hour=100,
            max_per_day=1000,
            min_reply_delay_sec=0.1,
            max_reply_delay_sec=0.2,
            auto_trip_on_failures=5,
        ),
        whitelist=WhitelistConfig(enabled=True, chats=tuple(whitelist)),
        reply=ReplyConfig(engine="rules", rules=(ReplyRule(("在吗",), "在的～"),)),
        llm=LLMConfig(base_url="http://127.0.0.1:11434/v1", model="fake"),
    )


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_runner(self, cfg, client, events=None):
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        pipeline = ReplyPipeline(
            cfg, gateway, ChatMemory(self.tmp / "mem.json"), journal=Journal(self.tmp / "j.jsonl")
        )
        return Runner(
            cfg,
            client,
            gateway=gateway,
            pipeline=pipeline,
            journal=Journal(self.tmp / "j.jsonl"),
            poll_interval=0.05,
            on_event=(events.append if events is not None else None),
        )

    # ---------- 开关语义 ----------
    def test_starts_stopped(self):
        runner = self.make_runner(make_config(), FakeClient([]))
        self.assertFalse(runner.running)
        self.assertEqual(runner.state, "stopped")

    def test_start_then_stop(self):
        events: list[RunnerEvent] = []
        runner = self.make_runner(make_config(), FakeClient([[]]), events)
        self.assertTrue(runner.start())
        self.assertTrue(runner.running)
        self.assertTrue(runner.stop())
        self.assertFalse(runner.running)
        self.assertEqual(runner.state, "stopped")
        kinds = [event.kind for event in events]
        self.assertIn("started", kinds)
        self.assertIn("stopped", kinds)

    def test_double_start_is_rejected(self):
        runner = self.make_runner(make_config(), FakeClient([[]]))
        self.assertTrue(runner.start())
        self.assertFalse(runner.start(), "已经在运行时应拒绝重复启动")
        runner.stop()

    def test_stop_when_not_running_is_safe(self):
        runner = self.make_runner(make_config(), FakeClient([]))
        self.assertTrue(runner.stop())
        self.assertEqual(runner.state, "stopped")

    def test_stop_is_idempotent(self):
        runner = self.make_runner(make_config(), FakeClient([[]]))
        runner.start()
        self.assertTrue(runner.stop())
        self.assertTrue(runner.stop())

    # ---------- 停止后不再工作 ----------
    def test_no_background_work_after_stop(self):
        import time as _time

        client = FakeClient([[IncomingMessage("张三", "在吗")]] * 20)
        runner = self.make_runner(make_config(), client)
        runner.start()
        runner.stop()

        polls_at_stop = runner.stats.polls
        received_at_stop = runner.stats.received
        _time.sleep(0.4)  # 等几个轮询周期，验证后台确实不再动
        self.assertEqual(runner.stats.polls, polls_at_stop, "停机后不应再自动轮询")
        self.assertEqual(runner.stats.received, received_at_stop, "停机后不应再读消息")
        self.assertEqual(len(client.sent), 0)

    def test_manual_poll_is_explicit_and_allowed(self):
        """poll_once 是显式手动调用（供「试一次」用），停机状态下也可用。"""
        client = FakeClient([[IncomingMessage("张三", "在吗")]])
        runner = self.make_runner(make_config("dry_run"), client)
        self.assertFalse(runner.running)
        messages = runner.poll_once()
        self.assertEqual(len(messages), 1)
        self.assertEqual(runner.stats.received, 1)

    def test_restart_after_stop_works(self):
        events: list[RunnerEvent] = []
        client = FakeClient([[IncomingMessage("张三", "在吗")] for _ in range(6)])
        runner = self.make_runner(make_config("dry_run"), client, events)
        runner.start()
        runner.stop()
        first_polls = runner.stats.polls
        self.assertTrue(runner.start(), "停止后应能再次启动")
        import time as _time

        _time.sleep(0.2)
        runner.stop()
        self.assertGreater(runner.stats.polls, 0)
        # 重新启动会重置统计
        self.assertLessEqual(runner.stats.polls, first_polls + 1 if first_polls else 1)

    # ---------- 单轮行为 ----------
    def test_tick_reads_and_plans_in_dry_run(self):
        events: list[RunnerEvent] = []
        client = FakeClient([[IncomingMessage("张三", "在吗")]])
        runner = self.make_runner(make_config("dry_run"), client, events)
        messages = runner.poll_once()
        self.assertEqual(len(messages), 1)
        self.assertEqual(runner.stats.received, 1)
        self.assertEqual(runner.stats.replied, 1)
        self.assertEqual(runner.stats.sent, 0)
        self.assertEqual(len(client.sent), 0, "dry_run 不应真的发送")
        replies = [event for event in events if event.kind == "reply"]
        self.assertTrue(any("未发送" in event.text for event in replies))

    def test_tick_sends_in_auto_mode(self):
        client = FakeClient([[IncomingMessage("张三", "在吗")]], can_send=True)
        runner = self.make_runner(make_config("auto"), client)
        runner.poll_once()
        self.assertEqual(client.sent, [("张三", "在的～")])
        self.assertEqual(runner.stats.sent, 1)

    def test_tick_does_not_send_when_client_cannot_send(self):
        client = FakeClient([[IncomingMessage("张三", "在吗")]], can_send=False)
        runner = self.make_runner(make_config("auto"), client)
        runner.poll_once()
        self.assertEqual(client.sent, [])
        self.assertEqual(runner.stats.sent, 0)
        self.assertEqual(runner.stats.replied, 1, "仍应产出拟回复，只是不发送")

    def test_whitelist_blocks(self):
        client = FakeClient([[IncomingMessage("陌生人", "在吗")]])
        runner = self.make_runner(make_config("auto"), client)
        runner.poll_once()
        self.assertEqual(runner.stats.denied, 1)
        self.assertEqual(client.sent, [])

    def test_unavailable_client_reports_and_continues(self):
        events: list[RunnerEvent] = []
        client = FakeClient([[]])
        client.available = False
        runner = self.make_runner(make_config(), client, events)
        runner.poll_once()
        self.assertTrue(any(event.kind == "warn" for event in events))
        self.assertEqual(runner.stats.received, 0)

    def test_loop_runs_multiple_ticks_then_stops(self):
        client = FakeClient([[IncomingMessage("张三", "在吗")] for _ in range(3)])
        runner = self.make_runner(make_config("dry_run"), client)
        runner.start()
        deadline = 3.0
        import time as _time

        start = _time.time()
        while runner.stats.received < 3 and _time.time() - start < deadline:
            _time.sleep(0.05)
        runner.stop()
        self.assertGreaterEqual(runner.stats.received, 3)
        self.assertFalse(runner.running)

    def test_journal_written(self):
        journal_path = self.tmp / "runner.jsonl"
        cfg = make_config()
        client = FakeClient([[IncomingMessage("张三", "在吗")]])
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        pipeline = ReplyPipeline(cfg, gateway, ChatMemory(self.tmp / "m.json"))
        runner = Runner(
            cfg, client, gateway=gateway, pipeline=pipeline,
            journal=Journal(journal_path), poll_interval=0.05,
        )
        runner.start()
        runner.stop()
        content = journal_path.read_text(encoding="utf-8")
        self.assertIn("runner_start", content)
        self.assertIn("runner_stop", content)


if __name__ == "__main__":
    unittest.main()
