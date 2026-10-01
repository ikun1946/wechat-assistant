"""安全网关 —— 所有对外发送必须先通过这里。

设计原则：默认拒绝（deny by default）。任何一条规则不通过就不发送；
所有决策由调用方写入审计日志，可回溯。
它不负责「怎么发」，只负责「准不准发」。
"""

from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from ..config import SafetyConfig, WhitelistConfig, parse_quiet_span
from ..textutil import names_match, normalize_name


@dataclass
class Decision:
    allowed: bool
    reason: str = ""


def in_quiet_hours(now_minutes: int, spans: list[tuple[int, int]]) -> bool:
    """判断「当天第几分钟」是否落在静默区间（支持跨零点，如 23:00-08:00）。"""
    for start, end in spans:
        if start <= end:
            if start <= now_minutes < end:
                return True
        elif now_minutes >= start or now_minutes < end:
            return True
    return False


class SafetyGateway:
    def __init__(self, safety: SafetyConfig, whitelist: WhitelistConfig, *, now=None, rng=None):
        self._safety = safety
        self._whitelist = whitelist
        self._now = now or time.time
        self._rng = rng or random.Random()
        self._quiet_spans = [parse_quiet_span(spec) for spec in safety.quiet_hours]
        self._sends: deque[float] = deque()
        self.tripped = False
        self.trip_reason = ""
        self.consecutive_failures = 0
        self.stats = {"allowed": 0, "denied": 0, "sent": 0}

    # ---------- 熔断 ----------
    def trip(self, reason: str) -> None:
        self.tripped = True
        self.trip_reason = reason

    def reset_trip(self) -> None:
        self.tripped = False
        self.trip_reason = ""
        self.consecutive_failures = 0

    def note_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self._safety.auto_trip_on_failures:
            self.trip(f"连续发送失败 {self.consecutive_failures} 次，自动熔断")

    def note_success(self) -> None:
        self.consecutive_failures = 0

    # ---------- 准入检查 ----------
    def check(self, chat_name: str, *, is_group: bool = False) -> Decision:
        """发送前必须调用。返回 Decision(allowed, reason)。

        is_group 预留给后续的群聊差异策略（如群聊更保守），当前不影响判定。
        """
        if self.tripped:
            return self._deny(f"熔断中：{self.trip_reason}")
        if self._whitelist.enabled and not self._whitelist.allow_all:
            allowed = any(names_match(chat_name, item) for item in self._whitelist.chats)
            if not allowed:
                return self._deny(f"不在白名单：{chat_name}")
        now = self._now()
        moment = datetime.fromtimestamp(now)
        if self._quiet_spans and in_quiet_hours(moment.hour * 60 + moment.minute, self._quiet_spans):
            return self._deny("处于静默时段")
        self._prune(now)
        if self._count_since(now, 60) >= self._safety.max_per_minute:
            return self._deny("超过每分钟限额")
        if self._count_since(now, 3600) >= self._safety.max_per_hour:
            return self._deny("超过每小时限额")
        if self._count_since(now, 86400) >= self._safety.max_per_day:
            return self._deny("超过每日限额")
        self.stats["allowed"] += 1
        return Decision(True, "ok")

    def _deny(self, reason: str) -> Decision:
        self.stats["denied"] += 1
        return Decision(False, reason)

    # ---------- 记账 ----------
    def record_sent(self) -> None:
        """真实发送成功后调用（dry_run 不调用）。"""
        self._sends.append(self._now())
        self.stats["sent"] += 1

    def _prune(self, now: float) -> None:
        while self._sends and now - self._sends[0] > 86400:
            self._sends.popleft()

    def _count_since(self, now: float, window_seconds: float) -> int:
        return sum(1 for t in self._sends if now - t < window_seconds)

    # ---------- 拟人化 ----------
    def next_delay(self) -> float:
        """下一次回复前的随机延迟（秒）。"""
        return self._rng.uniform(self._safety.min_reply_delay_sec, self._safety.max_reply_delay_sec)

    def summary(self) -> dict:
        return {
            "tripped": self.tripped,
            "trip_reason": self.trip_reason,
            "recent_sent_24h": len(self._sends),
            "stats": dict(self.stats),
        }
