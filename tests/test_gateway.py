"""安全网关单元测试（核心安全逻辑，必须全绿）。"""

from __future__ import annotations

import unittest
from datetime import datetime

from wxbot.config import SafetyConfig, WhitelistConfig
from wxbot.safety.gateway import SafetyGateway


class FakeClock:
    def __init__(self, start: datetime):
        self._t = start.timestamp()

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds

    def move_to(self, moment: datetime) -> None:
        self._t = moment.timestamp()


def make_gateway(clock=None, **safety_overrides) -> SafetyGateway:
    safety = SafetyConfig(
        quiet_hours=(),
        max_per_minute=3,
        max_per_hour=10,
        max_per_day=20,
        min_reply_delay_sec=2.0,
        max_reply_delay_sec=6.0,
        auto_trip_on_failures=3,
    )
    for key, value in safety_overrides.items():
        setattr(safety, key, value)
    whitelist = WhitelistConfig(enabled=True, chats=("张三",))
    return SafetyGateway(
        safety,
        whitelist,
        now=clock or FakeClock(datetime(2026, 10, 1, 14, 0, 0)),
    )


class SafetyGatewayTests(unittest.TestCase):
    def test_whitelist_blocks_unknown_chat(self):
        gateway = make_gateway()
        decision = gateway.check("李四")
        self.assertFalse(decision.allowed)
        self.assertIn("白名单", decision.reason)

    def test_whitelist_allows_listed_chat(self):
        gateway = make_gateway()
        self.assertTrue(gateway.check("张三").allowed)

    def test_whitelist_tolerates_fullwidth_punctuation(self):
        """白名单写「老王！」、OCR 读成「老王!」时也应放行（全角/半角差异）。"""
        safety = SafetyConfig(quiet_hours=(), max_per_minute=5, max_per_hour=50, max_per_day=500)
        gateway = SafetyGateway(
            safety,
            WhitelistConfig(enabled=True, chats=("老王！", "家庭群（5）")),
            now=FakeClock(datetime(2026, 10, 1, 14, 0, 0)),
        )
        self.assertTrue(gateway.check("老王!").allowed, "全角感叹号 vs 半角应视为同一会话")
        self.assertTrue(gateway.check("家庭群(5)").allowed, "全角括号 vs 半角应视为同一会话")
        self.assertFalse(gateway.check("其他人").allowed)

    def test_quiet_hours_block_at_night(self):
        clock = FakeClock(datetime(2026, 10, 1, 23, 30, 0))
        gateway = make_gateway(clock, quiet_hours=("23:00-08:00",))
        self.assertFalse(gateway.check("张三").allowed)
        clock.move_to(datetime(2026, 10, 2, 7, 0, 0))
        self.assertFalse(gateway.check("张三").allowed)
        clock.move_to(datetime(2026, 10, 2, 12, 0, 0))
        self.assertTrue(gateway.check("张三").allowed)

    def test_per_minute_limit(self):
        gateway = make_gateway()
        for _ in range(3):
            gateway.record_sent()
        decision = gateway.check("张三")
        self.assertFalse(decision.allowed)
        self.assertIn("每分钟", decision.reason)

    def test_per_minute_limit_resets_after_window(self):
        clock = FakeClock(datetime(2026, 10, 1, 14, 0, 0))
        gateway = make_gateway(clock)
        for _ in range(3):
            gateway.record_sent()
        self.assertFalse(gateway.check("张三").allowed)
        clock.advance(61)
        self.assertTrue(gateway.check("张三").allowed)

    def test_daily_limit(self):
        gateway = make_gateway(max_per_minute=100, max_per_hour=100, max_per_day=3)
        for _ in range(3):
            gateway.record_sent()
        decision = gateway.check("张三")
        self.assertFalse(decision.allowed)
        self.assertIn("每日", decision.reason)

    def test_manual_trip_and_reset(self):
        gateway = make_gateway()
        gateway.trip("手动急停")
        decision = gateway.check("张三")
        self.assertFalse(decision.allowed)
        self.assertIn("熔断", decision.reason)
        gateway.reset_trip()
        self.assertTrue(gateway.check("张三").allowed)

    def test_auto_trip_after_consecutive_failures(self):
        gateway = make_gateway()
        gateway.note_failure()
        gateway.note_failure()
        self.assertFalse(gateway.tripped)
        gateway.note_failure()
        self.assertTrue(gateway.tripped)

    def test_success_resets_failure_counter(self):
        gateway = make_gateway()
        gateway.note_failure()
        gateway.note_failure()
        gateway.note_success()
        gateway.note_failure()
        gateway.note_failure()
        self.assertFalse(gateway.tripped)

    def test_delay_within_configured_range(self):
        gateway = make_gateway()
        for _ in range(20):
            delay = gateway.next_delay()
            self.assertGreaterEqual(delay, 2.0)
            self.assertLessEqual(delay, 6.0)


if __name__ == "__main__":
    unittest.main()
