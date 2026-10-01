"""微信客户端交互抽象层。

实现必须遵守：
- 只使用不侵入微信进程的技术（UIA 只读接入 / 截图 OCR / 键鼠模拟）；
- send_text() 的每一次真实发送，都必须由调用方先通过 SafetyGateway.check()。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class IncomingMessage:
    chat_name: str
    text: str
    is_group: bool = False
    ts: float = field(default_factory=time.time)


class WeChatClient(ABC):
    """与微信客户端交互的统一接口（具体实现见 uia_client / vision_client）。"""

    @property
    def can_send(self) -> bool:
        """当前实现是否具备真实发送能力（未接入时 Runner 只记录不发送）。"""
        return True

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """返回 (是否可用, 说明)。"""

    @abstractmethod
    def poll_new_messages(self) -> list[IncomingMessage]:
        """拉取自上次调用以来的新消息（只读）。"""

    @abstractmethod
    def send_text(self, chat_name: str, text: str) -> bool:
        """向指定会话发送文本。返回是否成功。实现不得绕过安全网关。"""


class NullClient(WeChatClient):
    """占位实现：收发模块接入前保证程序可运行、不做任何危险动作。"""

    @property
    def can_send(self) -> bool:
        return False

    def is_available(self) -> tuple[bool, str]:
        return False, "收发模块尚未接入"

    def poll_new_messages(self) -> list[IncomingMessage]:
        return []

    def send_text(self, chat_name: str, text: str) -> bool:
        return False
