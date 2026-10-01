"""运行控制器（Runner）单元测试：开关语义、统计、安全网关串联。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wxbot.brain.memory import ChatMemory
from wxbot.brain.pipeline import PipelineResult, ReplyPipeline
from wxbot.config import (
    AppConfig,
    LLMConfig,
    ReplyConfig,
    ReplyRule,
    SafetyConfig,
    WhitelistConfig,
)
from wxbot.journal import Journal
from wxbot.runner import MAX_GENERATE_ATTEMPTS, Runner, RunnerEvent
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

    def make_runner(self, cfg, client, events=None, pipeline=None):
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        if pipeline is None:
            pipeline = ReplyPipeline(
                cfg,
                gateway,
                ChatMemory(self.tmp / "mem.json"),
                journal=Journal(self.tmp / "j.jsonl"),
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
        # 三条**不同**的消息：Runner 现在按「会话+文本」去重，
        # 重复投同一条只会统计一次（这正是修复后的行为）。
        client = FakeClient(
            [
                [IncomingMessage("张三", f"第 {i} 条")]
                for i in range(3)
            ]
        )
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

    def test_same_message_is_not_processed_twice(self):
        """回归：同一条消息跨多轮只处理一次。

        修复前，生成失败（或被网关拦截）之后同一条会被无限重试，
        日志表现为每 34 秒重复一次「识别到新消息 / 生成失败」。
        """
        events: list[RunnerEvent] = []
        message = IncomingMessage("张三", "在吗")
        client = FakeClient([[message] for _ in range(5)])
        runner = self.make_runner(make_config("dry_run"), client, events)
        for _ in range(5):
            runner.poll_once()
        self.assertEqual(runner.stats.received, 1, "同一条消息只应被处理一次")
        self.assertEqual(
            sum(1 for e in events if e.kind == "message"),
            1,
            "不应重复上报同一条消息",
        )

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


class FailingPipeline:
    """永远失败的流水线（模拟本地模型一直连不上）。"""

    def __init__(self, reason: str = "请求失败：timed out"):
        self.reason = reason
        self.calls = 0
        self.seen: list[str] = []

    def handle(self, message):
        self.calls += 1
        self.seen.append(message.text)
        return PipelineResult(action="error", reason=self.reason)

    def note_sent(self, message, result):
        pass


class GenerationRetryTests(unittest.TestCase):
    """生成失败的退避与上限 —— 回归「每 34 秒重试一次的死循环」。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def make_runner(self, cfg, client, events, pipeline):
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        return Runner(
            cfg,
            client,
            gateway=gateway,
            pipeline=pipeline,
            journal=Journal(self.tmp / "j.jsonl"),
            poll_interval=0.05,
            on_event=events.append,
        )

    def test_gives_up_after_max_attempts(self):
        events: list[RunnerEvent] = []
        message = IncomingMessage("张三", "你好")
        client = FakeClient([[message] for _ in range(20)])
        pipeline = FailingPipeline()
        runner = self.make_runner(make_config("auto"), client, events, pipeline)

        for _ in range(20):
            runner._retry_after.clear()  # 模拟退避时间已过
            runner.poll_once()

        self.assertEqual(
            pipeline.calls,
            MAX_GENERATE_ATTEMPTS,
            "超过上限后必须停止重试（原来是无限重试）",
        )
        self.assertTrue(
            any("放弃" in e.text for e in events),
            "应明确记录「已放弃」，而不是静默",
        )

    def test_backoff_blocks_immediate_retry(self):
        """第一次失败后立刻再轮询，不应该马上再打一次模型。"""
        events: list[RunnerEvent] = []
        message = IncomingMessage("张三", "你好")
        client = FakeClient([[message] for _ in range(4)])
        pipeline = FailingPipeline()
        runner = self.make_runner(make_config("auto"), client, events, pipeline)

        runner.poll_once()
        self.assertEqual(pipeline.calls, 1)
        runner.poll_once()
        self.assertEqual(pipeline.calls, 1, "退避窗口内不应再次调用模型")

    def test_new_message_still_processed_after_give_up(self):
        """放弃某条之后，新消息必须照常处理（不能连坐）。"""
        events: list[RunnerEvent] = []
        client = FakeClient(
            [[IncomingMessage("张三", "你好")] for _ in range(6)]
            + [[IncomingMessage("张三", "在吗")] for _ in range(3)]
        )
        pipeline = FailingPipeline()
        runner = self.make_runner(make_config("auto"), client, events, pipeline)

        for _ in range(9):
            runner._retry_after.clear()
            runner.poll_once()

        self.assertEqual(
            pipeline.seen.count("你好"),
            MAX_GENERATE_ATTEMPTS,
            "「你好」重试到上限即放弃",
        )
        self.assertEqual(
            pipeline.seen.count("在吗"),
            MAX_GENERATE_ATTEMPTS,
            "「在吗」是另一条消息，有自己独立的重试额度（不被连坐）",
        )
        self.assertEqual(
            sum(1 for e in events if "放弃" in e.text),
            2,
            "两条消息各自记录一次放弃",
        )

    def test_generation_failure_counts_toward_circuit_breaker(self):
        """生成失败必须计入熔断 —— 以前只统计发送失败，熔断阈值形同虚设。"""
        events: list[RunnerEvent] = []
        cfg = make_config("auto")
        cfg.safety.auto_trip_on_failures = 3
        client = FakeClient(
            [[IncomingMessage("张三", f"消息 {i}")] for i in range(3)] + [[] for _ in range(3)]
        )
        pipeline = FailingPipeline()
        gateway = SafetyGateway(cfg.safety, cfg.whitelist)
        runner = Runner(
            cfg,
            client,
            gateway=gateway,
            pipeline=pipeline,
            journal=Journal(self.tmp / "j.jsonl"),
            poll_interval=0.05,
            on_event=events.append,
        )

        for _ in range(6):
            runner.poll_once()

        self.assertTrue(gateway.tripped, "连续生成失败应触发熔断")
        self.assertEqual(gateway.consecutive_failures, 3)



if __name__ == "__main__":
    unittest.main()
