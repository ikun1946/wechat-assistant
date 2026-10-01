"""检查模型库里各条目的模态是否与名称元数据一致。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.model_store import ModelStore  # noqa: E402
from wxbot.providers import lookup_model_meta  # noqa: E402

store = ModelStore()
for provider in ("lmstudio", "ollama", "custom"):
    for entry in store.entries(provider):
        meta = lookup_model_meta(provider, entry.model)
        flag = "" if entry.modalities == meta.modalities else "   <-- 与名称元数据不一致"
        print(
            f"{provider:9s} {entry.model:24s} 库里={str(entry.modalities):22s} "
            f"应为={str(meta.modalities):22s} auto={entry.auto_filled}{flag}"
        )
