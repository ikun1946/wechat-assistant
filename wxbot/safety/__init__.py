"""安全防线：所有发送必须先通过 SafetyGateway。"""

from .gateway import Decision, SafetyGateway

__all__ = ["Decision", "SafetyGateway"]
