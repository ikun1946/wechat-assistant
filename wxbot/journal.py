"""本地 JSONL 审计日志：所有决策与动作可回溯。

一行一个 JSON 对象，只追加、不改写。默认写入**程序所在目录**的
logs/journal.jsonl。

⚠ 必须用 `APP_DIR` 而不是 `PROJECT_ROOT`：打包成 exe 后，
`__file__` 落在 PyInstaller 的临时解包目录里，程序一退出那个目录就被删，
日志会**全部丢失**。`APP_DIR` 在冻结后指向 exe 所在目录（见 config._app_dir）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import APP_DIR

DEFAULT_JOURNAL_PATH = APP_DIR / "logs" / "journal.jsonl"


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
