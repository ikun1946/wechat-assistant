"""模型库：每个「厂商 × 模型」各自的配置（上下文 / 模态 / 思考等级 / 最大输出）。

存储：data/models.json
首次从厂商拉取模型列表时，会按元数据库自动预填好各项；之后用户可以逐条改写。
图形界面「模型」页读取/写入这里。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..config import DATA_DIR
from ..providers import lookup_model_meta

DEFAULT_MODELS_PATH = DATA_DIR / "models.json"


@dataclass
class ModelEntry:
    provider: str
    model: str
    context_length: int = 32_768
    modalities: tuple[str, ...] = ("text",)
    thinking_level: str = "auto"
    max_output_tokens: int = 4_096
    temperature: float = 0.8
    note: str = ""
    auto_filled: bool = False  # 是否由元数据库自动预填

    @property
    def key(self) -> str:
        return f"{self.provider}::{self.model}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["modalities"] = list(self.modalities)
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> "ModelEntry":
        return cls(
            provider=str(raw.get("provider", "custom")),
            model=str(raw.get("model", "")),
            context_length=int(raw.get("context_length", 32_768)),
            modalities=tuple(str(m) for m in raw.get("modalities", ["text"])),
            thinking_level=str(raw.get("thinking_level", "auto")),
            max_output_tokens=int(raw.get("max_output_tokens", 4_096)),
            temperature=float(raw.get("temperature", 0.8)),
            note=str(raw.get("note", "")),
            auto_filled=bool(raw.get("auto_filled", False)),
        )

    @staticmethod
    def create_with_meta(provider: str, model: str) -> "ModelEntry":
        """按元数据库自动预填一条模型配置。"""
        meta = lookup_model_meta(provider, model)
        return ModelEntry(
            provider=provider,
            model=model,
            context_length=meta.context_length,
            modalities=meta.modalities,
            thinking_level=meta.default_thinking,
            max_output_tokens=meta.max_output_tokens,
            note=meta.note,
            auto_filled=True,
        )


class ModelStore:
    def __init__(self, path: Path | None = None):
        self._path = Path(path) if path is not None else DEFAULT_MODELS_PATH
        self._entries: dict[str, ModelEntry] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        items = data.get("models") if isinstance(data, dict) else None
        if isinstance(items, list):
            for raw in items:
                if isinstance(raw, dict):
                    entry = ModelEntry.from_dict(raw)
                    if entry.model:
                        self._entries[entry.key] = entry

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "models": [entry.to_dict() for entry in self._entries.values()],
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---------- 查询 ----------
    def entries(self, provider: str | None = None) -> list[ModelEntry]:
        items = list(self._entries.values())
        if provider:
            items = [e for e in items if e.provider == provider]
        return sorted(items, key=lambda e: (e.provider, e.model))

    def get(self, provider: str, model: str) -> ModelEntry | None:
        return self._entries.get(f"{provider}::{model}")

    def __len__(self) -> int:
        return len(self._entries)

    # ---------- 修改 ----------
    def upsert(self, entry: ModelEntry) -> ModelEntry:
        self._entries[entry.key] = entry
        self.save()
        return entry

    def ensure(self, provider: str, model: str) -> ModelEntry:
        """存在就返回；不存在则按元数据自动创建并保存。"""
        existing = self.get(provider, model)
        if existing is not None:
            return existing
        return self.upsert(ModelEntry.create_with_meta(provider, model))

    def sync_provider_models(self, provider: str, model_ids: list[str]) -> list[ModelEntry]:
        """把某厂商拉取到的模型列表批量入库（已存在的保留用户改动）。"""
        result: list[ModelEntry] = []
        for model_id in model_ids:
            result.append(self.ensure(provider, model_id))
        return result

    def refill_meta(self, provider: str, model: str) -> ModelEntry | None:
        """按名称重新推断并覆盖元数据（用户手动触发）。"""
        entry = self.get(provider, model)
        if entry is None:
            return None
        meta = lookup_model_meta(provider, model)
        entry.context_length = meta.context_length
        entry.modalities = meta.modalities
        entry.thinking_level = meta.default_thinking
        entry.max_output_tokens = meta.max_output_tokens
        entry.note = meta.note
        entry.auto_filled = True
        return self.upsert(entry)

    def remove(self, provider: str, model: str) -> bool:
        key = f"{provider}::{model}"
        if key not in self._entries:
            return False
        del self._entries[key]
        self.save()
        return True
