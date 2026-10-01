"""按会话的短期记忆：供 LLM 上下文与图形界面查看。

存储：data/chat_memory.json（本地文件，已 gitignore）。
role 取值：them=对方 / me=本人。

⚠ 两个关键设计（都是实测踩出来的）：
1. **会话名必须归一化后作为 key** —— 否则「老王！」和「老王!」会变成两份独立记忆，
   模型只能看到一半对话，表现就是"它不记得说过什么"。
2. **入库前要清洗文本** —— 会话摘要里会混进未读角标数字（"…父亲吗 3 3"）和时间前缀。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ..config import DATA_DIR
from ..textutil import normalize_name

DEFAULT_MEMORY_PATH = DATA_DIR / "chat_memory.json"

# 摘要里可能混入未读角标数字（如「你不是他们的父亲吗 3 3」）和时间前缀
_TRAILING_DIGITS = re.compile(r"(?:\s+\d+)+\s*$")
_TIME_PREFIX = re.compile(
    r"^\s*(?:\d{1,2}:\d{2}|昨天|前天|星期[一二三四五六日天]|周[一二三四五六日天])\s*"
)


def clean_message_text(text: str) -> str:
    """清洗存入记忆的文本：去掉时间前缀与末尾的未读角标数字。"""
    cleaned = _TIME_PREFIX.sub("", text or "").strip()
    cleaned = _TRAILING_DIGITS.sub("", cleaned).strip()
    return cleaned or (text or "").strip()


class ChatMemory:
    def __init__(self, path: Path | None = None, *, max_per_chat: int = 50):
        self._path = Path(path) if path is not None else DEFAULT_MEMORY_PATH
        self._max_per_chat = max(1, int(max_per_chat))
        self._chats: dict[str, list[dict]] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        chats = data.get("chats") if isinstance(data, dict) else None
        if not isinstance(chats, dict):
            return
        merged: dict[str, list[dict]] = {}
        for name, items in chats.items():
            if not isinstance(items, list):
                continue
            # 归一化后作为 key：把「老王！」与「老王!」合并成同一份记忆
            key = normalize_name(str(name))
            if not key:
                continue
            bucket = merged.setdefault(key, [])
            for item in items:
                if isinstance(item, dict):
                    bucket.append(item)
        for bucket in merged.values():
            bucket.sort(key=lambda item: float(item.get("ts", 0.0) or 0.0))
            if len(bucket) > self._max_per_chat:
                del bucket[: len(bucket) - self._max_per_chat]
        self._chats = merged

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 2, "chats": self._chats}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---------- 接口 ----------
    def add(self, chat_name: str, role: str, text: str) -> None:
        key = normalize_name(chat_name)
        if not key:
            return
        items = self._chats.setdefault(key, [])
        items.append(
            {"role": role, "text": clean_message_text(text), "ts": time.time()}
        )
        if len(items) > self._max_per_chat:
            del items[: len(items) - self._max_per_chat]
        self.save()

    def recent(self, chat_name: str, n: int) -> list[tuple[str, str]]:
        items = self._chats.get(normalize_name(chat_name), [])
        return [
            (str(x.get("role", "them")), str(x.get("text", "")))
            for x in items[-max(1, n) :]
        ]

    def chats(self) -> list[str]:
        return sorted(self._chats)

    def count(self, chat_name: str) -> int:
        return len(self._chats.get(normalize_name(chat_name), []))

    def clear(self, chat_name: str | None = None) -> None:
        if chat_name is None:
            self._chats.clear()
        else:
            self._chats.pop(normalize_name(chat_name), None)
        self.save()
