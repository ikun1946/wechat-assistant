"""运行控制器：把「读消息 → 安全网关 → 回复流水线 → 记录/发送」跑成一个可控的循环。

设计要点：
- 纯标准库线程实现（不依赖 GUI 框架），图形界面/命令行共用；
- start() / stop() 明确、可重复调用；stop() 会等待循环真正退出；
- 所有对外动作都经过 SafetyGateway 与 ReplyPipeline，本类不绕过任何安全约束；
- 默认只监测 + 决策；只有在 mode=auto 且客户端具备发送能力时才真的发送。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .brain.pipeline import ReplyPipeline
from .config import AppConfig
from .journal import Journal
from .safety.gateway import SafetyGateway
from .wechat.base import IncomingMessage, WeChatClient

STATE_STOPPED = "stopped"
STATE_RUNNING = "running"
STATE_ERROR = "error"

DEFAULT_POLL_INTERVAL = 3.0


@dataclass
class RunnerStats:
    polls: int = 0
    received: int = 0
    replied: int = 0
    denied: int = 0
    skipped: int = 0
    errors: int = 0
    sent: int = 0
    started_at: float | None = None
    last_error: str = ""
    last_message: str = ""


@dataclass
class RunnerEvent:
    kind: str  # started / stopped / info / warn / error / message / reply
    text: str
    data: dict = field(default_factory=dict)


class Runner:
    """可控的主循环。图形界面与命令行共用。"""

    def __init__(
        self,
        config: AppConfig,
        client: WeChatClient,
        *,
        gateway: SafetyGateway | None = None,
        pipeline: ReplyPipeline | None = None,
        journal: Journal | None = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        on_event: Callable[[RunnerEvent], None] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self._config = config
        self._client = client
        self._journal = journal or Journal()
        self._gateway = gateway or SafetyGateway(config.safety, config.whitelist)
        self._pipeline = pipeline or ReplyPipeline(
            config, self._gateway, _memory(), journal=self._journal
        )
        self._poll_interval = max(0.5, float(poll_interval))
        self._on_event = on_event
        self._sleep = sleep or time.sleep

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state = STATE_STOPPED
        self.stats = RunnerStats()

    # ---------- 对外接口 ----------
    @property
    def gateway(self) -> SafetyGateway:
        return self._gateway

    @property
    def running(self) -> bool:
        return self.state == STATE_RUNNING

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop.clear()
        self.state = STATE_RUNNING
        self.stats = RunnerStats(started_at=time.time())
        self._thread = threading.Thread(target=self._loop, name="wxbot-runner", daemon=True)
        self._thread.start()
        self._log("runner_start", mode=self._config.mode, interval=self._poll_interval)
        self._emit("started", f"已启动（模式：{self._config.mode}，轮询间隔 {self._poll_interval:g}s）")
        return True

    def stop(self, timeout: float = 6.0) -> bool:
        if self._thread is None:
            self.state = STATE_STOPPED
            return True
        self._stop.set()
        self._thread.join(timeout=timeout)
        alive = self._thread.is_alive()
        if alive:
            self._emit("warn", "停止超时：后台线程仍在退出中")
            return False
        self._thread = None
        self.state = STATE_STOPPED
        self._log("runner_stop", **self._stats_dict())
        self._emit("stopped", "已停止：不再识别微信，也不执行任何后续动作")
        return True

    def poll_once(self) -> list[IncomingMessage]:
        """手动执行一轮（不启动线程），返回本轮识别到的消息。"""
        return self._tick()

    # ---------- 内部 ----------
    def _emit(self, kind: str, text: str, **data) -> None:
        if self._on_event is not None:
            try:
                self._on_event(RunnerEvent(kind=kind, text=text, data=data))
            except Exception:
                pass

    def _log(self, event: str, **fields) -> None:
        try:
            self._journal.log(event, **fields)
        except Exception:
            pass

    def _stats_dict(self) -> dict:
        return {
            "polls": self.stats.polls,
            "received": self.stats.received,
            "replied": self.stats.replied,
            "denied": self.stats.denied,
            "skipped": self.stats.skipped,
            "errors": self.stats.errors,
            "sent": self.stats.sent,
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # 单轮异常不应终止整个循环
                self.stats.errors += 1
                self.stats.last_error = str(exc)
                self._log("runner_tick_error", error=str(exc))
                self._emit("error", f"本轮执行出错（已跳过）：{exc}")
            self._stop.wait(self._poll_interval)
        self.state = STATE_STOPPED

    def _tick(self) -> list[IncomingMessage]:
        self.stats.polls += 1

        available, reason = self._client.is_available()
        if not available:
            self.stats.last_error = reason
            self._emit("warn", f"暂时无法读取微信：{reason}")
            return []

        messages = self._client.poll_new_messages()
        if not messages:
            return []

        for message in messages:
            self.stats.received += 1
            self.stats.last_message = f"{message.chat_name}：{message.text}"
            self._emit(
                "message",
                f"识别到新消息 ← {message.chat_name}：{message.text}",
                chat=message.chat_name,
            )
            result = self._pipeline.handle(message)
            if result.action == "replied":
                self.stats.replied += 1
                can_send = getattr(self._client, "can_send", False)
                if self._config.mode == "auto" and can_send:
                    ok = self._client.send_text(message.chat_name, result.reply_text)
                    if ok:
                        self.stats.sent += 1
                        self._pipeline.note_sent(message, result)
                        self._emit("reply", f"已发送 → {message.chat_name}：{result.reply_text}")
                    else:
                        self._gateway.note_failure()
                        detail = getattr(self._client, "last_send_detail", "")
                        self._emit(
                            "error",
                            f"发送失败 → {message.chat_name}：{detail or '未知原因'}",
                        )
                else:
                    why = "当前为 dry_run 模式" if self._config.mode != "auto" else "发送模块尚未接入"
                    self._emit(
                        "reply",
                        f"拟回复（{why}，未发送）→ {message.chat_name}：{result.reply_text}",
                        delay=result.delay_sec,
                    )
            elif result.action == "denied":
                self.stats.denied += 1
                self._emit("info", f"已拦截（{result.reason}）← {message.chat_name}")
            elif result.action == "skipped":
                self.stats.skipped += 1
                self._emit("info", f"未回复（{result.reason}）← {message.chat_name}")
            else:
                self.stats.errors += 1
                self.stats.last_error = result.reason
                self._emit("error", f"生成失败：{result.reason}")
        return messages


def _memory():
    from .brain.memory import ChatMemory

    return ChatMemory()


def build_default_runner(
    config: AppConfig,
    *,
    on_event=None,
    client: WeChatClient | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
) -> Runner:
    """按配置装配一个默认 Runner（视觉客户端 + 安全网关 + 回复流水线）。"""
    if client is None:
        from .wechat.vision_client import VisionClient

        client = VisionClient()
    return Runner(config, client, on_event=on_event, poll_interval=poll_interval)
