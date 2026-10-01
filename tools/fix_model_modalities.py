"""一次性修正：把模型库里被旧 bug 污染的模态改回正确值。

背景：旧版 `lookup_model_meta` 对所有本地模型一律返回 ("text",)，
再加上「获取模型列表」会无条件重新预填，导致 `minicpm-v-4.6` 这类视觉模型
在模型库里被存成"不支持图片"。

本脚本**只**修 modalities 一项，不碰上下文 / 思考等级 / 最大输出等用户参数。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.model_store import ModelStore  # noqa: E402
from wxbot.providers import lookup_model_meta  # noqa: E402

MODELS_PATH = Path(__file__).resolve().parents[1] / "data" / "models.json"
DRY_RUN = "--apply" not in sys.argv

store = ModelStore()
changed: list[str] = []

for provider, model in [
    (e.provider, e.model)
    for e in list(store._entries.values())
]:
    entry = store.get(provider, model)
    if entry is None:
        continue
    expected = tuple(lookup_model_meta(provider, model).modalities)
    if tuple(entry.modalities) == expected:
        continue
    changed.append(
        f"{provider}::{model}  modalities {tuple(entry.modalities)} -> {expected}"
    )
    if not DRY_RUN:
        entry.modalities = expected

if not changed:
    print("模型库里的模态都与名称元数据一致，无需修改。")
    raise SystemExit(0)

print("需要修正的条目：")
for line in changed:
    print("  " + line)

if DRY_RUN:
    print("\n这是预览。确认后加 --apply 真正写入。")
    raise SystemExit(0)

backup = MODELS_PATH.with_suffix(".json.bak")
shutil.copy2(MODELS_PATH, backup)
store.save()
print(f"\n已写入，备份在 {backup.name}")
