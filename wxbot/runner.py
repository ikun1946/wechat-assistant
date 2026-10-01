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
from .safety.gateway import SafetyGateway, parse_quiet_span
from .wechat.base import IncomingMessage, WeChatClient

STATE_STOPPED = "stopped"
STATE_RUNNING = "running"
STATE_ERROR = "error"

DEFAULT_POLL_INTERVAL = 3.0

# 生成失败的重试策略。
# 以前没有任何上限：模型一直不恢复（比如本地服务挂了）就会变成
# 「每 34 秒重试同一条消息」的死循环，日志被刷满、CPU 空转。
# 现在：退避重试，超过上限就放弃这一条（**新消息不受影响**照常处理）。
MAX_GENERATE_ATTEMPTS = 3
RETRY_BACKOFF_SEC = (5.0, 20.0, 60.0)


def _fingerprint(message: IncomingMessage) -> str:
    """消息指纹：同一个会话里的同一条消息，跨轮询要认得出是同一条。"""
    from .textutil import normalize_name

    return f"{normalize_name(message.chat_name)}|{normalize_name(message.text)}"


def _one_line(text: str, limit: int = 120) -> str:
    """把思考过程压成一行摘要（完整内容走事件数据，不丢）。"""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


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
    # 上下文窗口占用（图形界面「运行」页画进度条用）
    context_used: int = 0
    context_total: int = 0
    # 最近一次的思考过程；非空说明这个模型会先想再答
    last_reasoning: str = ""

    @property
    def context_ratio(self) -> float:
        if self.context_total <= 0 or self.context_used <= 0:
            return 0.0
        return min(1.0, self.context_used / self.context_total)

    @property
    def context_display(self) -> str:
        if self.context_used <= 0:
            return "—"
        if self.context_total <= 0:
            return f"{self.context_used:,} tokens"
        return f"{self.context_used:,} / {self.context_total:,} · {self.context_ratio:.0%}"


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
        # 按「会话 + 消息文本」记住已经处理到哪一步了。
        # 没有它，一次生成失败就会让同一条消息被无限重试（实测症状：
        # 日志里每 34 秒重复一次「识别到新消息 ← 你好 / 生成失败 timed out」），
        # 被网关拦截的消息也会一轮轮重复上报、白白消耗轮询。
        self._decisions: dict[str, str] = {}   # 指纹 → 已下的结论（终态，不再重试）
        self._attempts: dict[str, int] = {}    # 指纹 → 已尝试次数
        self._retry_after: dict[str, float] = {}  # 指纹 → 下次允许重试的时刻

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

    def apply_config(self, config) -> None:
        """把新配置**就地**换进运行中的循环，不重启线程。

        为什么不用「stop + 重新 build 一个 Runner」（v2.6.4 的做法）：
        每次重建都会新建 Runner，而 WGC 抓屏在「同一窗口反复建/销会话」这个模式上
        **原生就会崩**（faulthandler 实测：崩在 `windows_capture/__init__.py:241`
        的 `capture.start()` 里，0xC0000005）。所以第二轮启动必崩 —— 也就是说
        连用户手动「关开关再开」都会闪退。

        这里改成原地替换：`_loop` 每轮都读 `self._config`，
        下一轮 poll 就用新模型，不需要停线程，也就不碰 WGC 会话。

        注意要一路换到底，否则换了 runner 没用（pipeline/gateway/skills 各自持有一份）：
        runner._config → pipeline._config → pipeline._skills（人设/记忆等）
        → gateway._safety / gateway._whitelist
        """
        self._config = config
        pipeline = self._pipeline
        pipeline._config = config
        # 技能按 cfg.skills 重建（人设、安全、群聊、学习开关都在这里）
        if hasattr(pipeline, "_skills") and getattr(pipeline, "_config", None) is config:
            from .brain.skills import SkillRegistry

            pipeline._skills = SkillRegistry(
                config.skills, learned_store=getattr(pipeline, "_learned", None)
            )
        # 网关里也各存了一份 safety / whitelist
        gateway = self._gateway
        gateway._safety = config.safety
        gateway._whitelist = config.whitelist
        gateway._quiet_spans = [parse_quiet_span(s) for s in config.safety.quiet_hours]

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
        self._decisions.clear()
        self._attempts.clear()
        self._retry_after.clear()
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
            fingerprint = _fingerprint(message)
            hold = self._hold_reason(fingerprint)
            if hold:
                # 已经有结论 / 还在退避窗口内 / 已经放弃 —— 静默跳过，
            # 不要再刷「识别到新消息」，否则日志会被同一条刷屏。
                continue
            self.stats.received += 1
            self.stats.last_message = f"{message.chat_name}：{message.text}"
            self._emit(
                "message",
                f"识别到新消息 ← {message.chat_name}：{message.text}",
                chat=message.chat_name,
            )
            result = self._pipeline.handle(message)
            if result.prompt_tokens:
                self.stats.context_used = result.prompt_tokens
                self.stats.context_total = result.context_length
            if result.reasoning:
                self.stats.last_reasoning = result.reasoning
                # 思考过程单独发一个事件，界面里用弱化样式显示，别和正文混为一谈
                self._emit(
                    "thinking",
                    f"模型思考（{len(result.reasoning)} 字）：{_one_line(result.reasoning)}",
                    chat=message.chat_name,
                    reasoning=result.reasoning,
                )
            if result.action == "replied":
                self._attempts.pop(fingerprint, None)
                self._retry_after.pop(fingerprint, None)
                self._decisions[fingerprint] = "replied"
                self.stats.replied += 1
                can_send = getattr(self._client, "can_send", False)
                if self._config.mode == "auto" and can_send:
                    ok = self._client.send_text(message.chat_name, result.reply_text)
                    if ok:
                        self.stats.sent += 1
                        self._pipeline.note_sent(message, result)
                        self._gateway.note_success()
                        self._emit("reply", f"已发送 → {message.chat_name}：{result.reply_text}")
                    else:
                        # 发送失败 → 记为终态：同一条不再重发（重发会打扰对方）
                        self._gateway.note_failure()
                        self._decisions[fingerprint] = "send_failed"
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
                # 拦截是**终态**：不在白名单就永远不该回，重试毫无意义
                self._decisions[fingerprint] = f"denied:{result.reason}"
                self.stats.denied += 1
                self._emit("info", f"已拦截（{result.reason}）← {message.chat_name}")
            elif result.action == "skipped":
                self._decisions[fingerprint] = f"skipped:{result.reason}"
                self.stats.skipped += 1
                self._emit("info", f"未回复（{result.reason}）← {message.chat_name}")
            else:
                # 生成失败：退避后重试，但**必须有上限** —— 否则模型一直不恢复
                # 就会变成每 34 秒重试一次的死循环（实测踩过）。
                self.stats.errors += 1
                self.stats.last_error = result.reason
                self._gateway.note_failure()  # 让熔断阈值真的能拦住生成失败
                attempt = self._attempts.get(fingerprint, 0) + 1
                self._attempts[fingerprint] = attempt
                if attempt >= MAX_GENERATE_ATTEMPTS:
                    self._decisions[fingerprint] = f"gave_up:{result.reason}"
                    self._emit(
                        "error",
                        f"生成失败已重试 {attempt} 次，放弃这条 ← {message.chat_name}："
                        f"{result.reason}（新消息会正常处理）",
                    )
                else:
                    delay = RETRY_BACKOFF_SEC[min(attempt - 1, len(RETRY_BACKOFF_SEC) - 1)]
                    self._retry_after[fingerprint] = time.time() + delay
                    self._emit(
                        "error",
                        f"生成失败（第 {attempt}/{MAX_GENERATE_ATTEMPTS} 次，{delay:g}s 后重试）："
                        f"{result.reason}",
                    )
        return messages

    def _hold_reason(self, fingerprint: str) -> str:
        """这条消息现在该不该跳过。返回非空字符串表示要跳过。"""
        decision = self._decisions.get(fingerprint)
        if decision:
            return f"已有结论（{decision}）"
        if self._attempts.get(fingerprint, 0) >= MAX_GENERATE_ATTEMPTS:
            return "重试次数已用尽"
        wait_until = self._retry_after.get(fingerprint, 0.0)
        if wait_until > time.time():
            return f"退避中（还剩 {wait_until - time.time():.0f}s）"
        return ""


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
