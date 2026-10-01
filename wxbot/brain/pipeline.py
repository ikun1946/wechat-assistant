"""回复流水线：一条新消息进来后，决定「回不回、回什么」。

分工：
- 安全网关（wxbot.safety）负责「准不准发」—— 白名单、静默、限速、熔断；
- 技能系统（wxbot.brain.skills）负责「要不要回、怎么回」；
- 本模块串起全流程：网关 → 技能闸门 → 生成（规则 / LLM）→ 回复审查 → 计划延迟。

真实发送由主循环负责；本模块只产出「计划」，不碰微信。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import AppConfig
from ..safety.gateway import SafetyGateway
from ..wechat.base import IncomingMessage
from .llm import LLMEngine, LLMError
from .memory import ChatMemory
from .rules import RuleEngine
from .skills import ReplyContext, SkillRegistry

DEFAULT_BASE_PROMPT = (
    "你正在代替微信主人回复他朋友发来的消息。要像本人一样自然回话，"
    "而不是像一个助手在回答问题。\n"
    "硬性要求：\n"
    "1. 绝对不要说自己是 AI、机器人、助手、程序、模型或「代回复」；\n"
    "2. 对方问「你是谁」「你是机器人吗」时，按下面给出的身份回答，不要否认也不要解释；\n"
    "3. 只回应当前这一条消息，不要编造没发生的事。"
)

Generator = Callable[..., str]


@dataclass
class PipelineResult:
    action: str  # replied / skipped / denied / error
    reason: str = ""
    reply_text: str = ""
    delay_sec: float = 0.0


class ReplyPipeline:
    def __init__(
        self,
        config: AppConfig,
        gateway: SafetyGateway,
        memory: ChatMemory,
        *,
        journal=None,
        generator: Generator | None = None,
        learned_store=None,
    ):
        self._config = config
        self._gateway = gateway
        self._memory = memory
        self._journal = journal
        self._skills = SkillRegistry(config.skills, learned_store)
        self._rules = RuleEngine(config.reply)
        self._generator = generator  # 测试用注入；生产走 LLMEngine
        self._replies_since_learn = 0
        self.learn_due = False

    # ---------- 日志 ----------
    def _log(self, event: str, **fields) -> None:
        if self._journal is not None:
            self._journal.log(event, **fields)

    def _remember_incoming(self, msg: IncomingMessage) -> None:
        if self._skills.memory.enabled:
            self._memory.add(msg.chat_name, "them", msg.text)

    # ---------- 主流程 ----------
    def handle(self, msg: IncomingMessage) -> PipelineResult:
        # 1. 安全网关（白名单 / 静默 / 限速 / 熔断）
        decision = self._gateway.check(msg.chat_name, is_group=msg.is_group)
        if not decision.allowed:
            self._log("denied", chat=msg.chat_name, text=msg.text, reason=decision.reason)
            return PipelineResult("denied", decision.reason)

        # 2. 取历史（须在记录本条消息之前）+ 记录收到消息
        history_limit = self._skills.memory.max_messages if self._skills.memory.enabled else 0
        history = tuple(self._memory.recent(msg.chat_name, history_limit)) if history_limit else ()
        self._remember_incoming(msg)

        ctx = ReplyContext(
            chat_name=msg.chat_name,
            incoming_text=msg.text,
            is_group=msg.is_group,
            history=history,
        )

        # 3. 技能闸门（群聊策略等）
        gate = self._skills.gate(ctx)
        if not gate.allow:
            self._log("skipped", chat=msg.chat_name, text=msg.text, reason=gate.reason)
            return PipelineResult("skipped", gate.reason)

        # 4. 生成回复
        try:
            reply = self._generate(ctx)
        except LLMError as exc:
            self._log("error", chat=msg.chat_name, text=msg.text, reason=str(exc))
            return PipelineResult("error", str(exc))

        if not reply:
            self._log("skipped", chat=msg.chat_name, text=msg.text, reason="没有可用的回复")
            return PipelineResult("skipped", "没有可用的回复")

        # 5. 回复审查（安全技能）
        review = self._skills.check_reply(ctx, reply)
        if not review.allow:
            self._log(
                "blocked",
                chat=msg.chat_name,
                text=msg.text,
                reply=reply,
                reason=review.reason,
            )
            return PipelineResult("skipped", f"回复被安全技能拦截：{review.reason}")

        # 6. 通过：产出「计划」（含拟人化延迟），发送由主循环执行
        delay = self._gateway.next_delay()
        self._log("planned", chat=msg.chat_name, text=msg.text, reply=reply, delay=round(delay, 2))
        return PipelineResult("replied", "ok", reply, delay)

    def _generate(self, ctx: ReplyContext) -> str | None:
        if self._config.reply.engine == "rules":
            return self._rules.generate(ctx.incoming_text)

        base = self._config.llm.system_prompt.strip() or DEFAULT_BASE_PROMPT
        system_prompt = self._skills.build_system_prompt(ctx, base)
        history = [
            ("user" if role == "them" else "assistant", text) for role, text in ctx.history
        ]
        if self._generator is not None:
            return self._generator(
                ctx.incoming_text, system_prompt=system_prompt, history=history
            )
        return LLMEngine(self._config.llm).generate(
            ctx.incoming_text, system_prompt=system_prompt, history=history
        )

    # ---------- 发送记账（由主循环在真实发送成功后调用） ----------
    def note_sent(self, msg: IncomingMessage, result: PipelineResult) -> None:
        self._gateway.record_sent()
        if self._skills.memory.enabled:
            self._memory.add(msg.chat_name, "me", result.reply_text)
        self._log("sent", chat=msg.chat_name, reply=result.reply_text)
        threshold = self._config.skills.learned.auto_after_replies
        if self._config.skills.learned.enabled and threshold > 0:
            self._replies_since_learn += 1
            if self._replies_since_learn >= threshold:
                self._replies_since_learn = 0
                self.learn_due = True

    def consume_learn_due(self) -> bool:
        """主循环用：是否该触发一次自动学习（触发后清零）。"""
        if self.learn_due:
            self.learn_due = False
            return True
        return False
