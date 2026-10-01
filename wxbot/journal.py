"""本地 JSONL 审计日志：所有决策与动作可回溯。

一行一个 JSON 对象，只追加、不改写。默认写入项目根目录 logs/journal.jsonl。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_JOURNAL_PATH = PROJECT_ROOT / "logs" / "journal.jsonl"


class Journal:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else DEFAULT_JOURNAL_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def log(self, event: str, **fields) -> None:
        line = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
