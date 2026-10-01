"""自学习技能库：AI 复盘聊天记录后整理出的技能条目（人工可逐条开关）。

存储：data/learned_skills.json（本地文件，已 gitignore）。
条目类型：
- faq   问答习惯：对方说什么 → 我一般怎么回（回复时按关键词参考，不直接照发）
- note  会话备注：某个会话的背景信息（只对该会话生效）
- style 风格补充：从实际回复中总结的说话风格（全局生效）
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ..config import DATA_DIR

DEFAULT_LEARNED_PATH = DATA_DIR / "learned_skills.json"

ITEM_TYPES = ("faq", "note", "style")


@dataclass
class LearnedItem:
    id: str
    type: str
    scope: str = "global"
    title: str = ""
    content: str = ""
    keywords: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    enabled: bool = True
    source: str = "ai"
    created_at: str = ""

    @staticmethod
    def create(
        type: str,
        scope: str,
        title: str,
        content: str,
        *,
        keywords: tuple[str, ...] = (),
        examples: tuple[str, ...] = (),
    ) -> "LearnedItem":
        return LearnedItem(
            id=uuid.uuid4().hex[:10],
            type=type,
            scope=scope or "global",
            title=title,
            content=content,
            keywords=tuple(keywords),
            examples=tuple(examples),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "LearnedItem":
        return cls(
            id=str(raw.get("id", uuid.uuid4().hex[:10])),
            type=str(raw.get("type", "")),
            scope=str(raw.get("scope", "global")),
            title=str(raw.get("title", "")),
            content=str(raw.get("content", "")),
            keywords=tuple(str(k) for k in raw.get("keywords", [])),
            examples=tuple(str(e) for e in raw.get("examples", [])),
            enabled=bool(raw.get("enabled", True)),
            source=str(raw.get("source", "ai")),
            created_at=str(raw.get("created_at", "")),
        )


class LearnedStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else DEFAULT_LEARNED_PATH
        self._items: list[LearnedItem] = []
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            self._items = [LearnedItem.from_dict(x) for x in items if isinstance(x, dict)]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "items": [item.to_dict() for item in self._items]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---------- 查询 ----------
    @staticmethod
    def _dedupe_key(item: LearnedItem) -> tuple[str, str, str]:
        return (item.type, item.scope, "".join(item.content.split())[:100])

    def items(self, *, enabled_only: bool = False) -> list[LearnedItem]:
        if enabled_only:
            return [item for item in self._items if item.enabled]
        return list(self._items)

    def get(self, item_id: str) -> LearnedItem | None:
        for item in self._items:
            if item.id == item_id:
                return item
        return None

    def __len__(self) -> int:
        return len(self._items)

    # ---------- 修改 ----------
    def add(self, item: LearnedItem) -> bool:
        """返回 True=新增；False=重复（已存在同类型同范围同内容的条目）。"""
        key = self._dedupe_key(item)
        if any(self._dedupe_key(existing) == key for existing in self._items):
            return False
        self._items.append(item)
        self.save()
        return True

    def set_enabled(self, item_id: str, enabled: bool) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        item.enabled = enabled
        self.save()
        return True

    def remove(self, item_id: str) -> bool:
        before = len(self._items)
        self._items = [item for item in self._items if item.id != item_id]
        if len(self._items) == before:
            return False
        self.save()
        return True
