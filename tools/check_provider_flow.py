"""厂商流程连通性自检：拉取模型列表 → 按名称自动预填元数据 → 入库。

用法：.venv/Scripts/python.exe tools/check_provider_flow.py [厂商key]
不带参数时读取 config.toml 里当前配置的厂商。

只读厂商的 /models 接口；会把发现的模型写入本地模型库 data/models.json（方便图形界面直接选）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.model_store import ModelStore
from wxbot.brain.llm import LLMEngine
from wxbot.config import ConfigError, load_config
from wxbot.providers import MODALITY_LABELS, get_provider, lookup_model_meta


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"[配置] 读取失败：{exc}")
        return 2

    provider_key = sys.argv[1] if len(sys.argv) > 1 else cfg.llm.provider
    provider = get_provider(provider_key)
    base_url = provider.base_url or cfg.llm.base_url
    api_key_env = provider.key_env if provider.base_url else cfg.llm.api_key_env

    print(f"[厂商] {provider.label}（{provider.key}）")
    print(f"[地址] {base_url or '（未配置）'}")
    print(f"[鉴权] {'本地服务，无需 Key' if provider.local else (api_key_env or '（未设置环境变量名）')}")
    if not base_url:
        print("[结果] 该厂商需要手动填写 base_url，已终止。")
        return 2

    engine = LLMEngine(
        type(cfg.llm)(
            provider=provider.key,
            base_url=base_url,
            model=cfg.llm.model or "placeholder",
            api_style=provider.api_style,
            api_key_env=api_key_env,
            timeout_sec=8.0,
        )
    )

    try:
        models = engine.list_models()
    except Exception as exc:  # noqa: BLE001
        print(f"[结果] ❌ 连接失败：{exc}")
        if provider.local:
            print("        本地服务请确认已启动（LM Studio → Developer → Start Server）。")
        return 3

    print(f"[结果] ✅ 连接成功，发现 {len(models)} 个模型")
    store = ModelStore()
    before = len(store)
    store.sync_provider_models(provider.key, models)
    print(f"[入库] 模型库新增 {len(store) - before} 个（原有 {before} 个）")
    print()
    print("按名称自动预填的参数：")
    for model_id in models[:20]:
        meta = lookup_model_meta(provider.key, model_id)
        modalities = "/".join(MODALITY_LABELS.get(m, m) for m in meta.modalities)
        print(
            f"  {model_id:<42s} 上下文={meta.context_length:>9,}  模态={modalities:<24s}"
            f"  思考默认={meta.default_thinking}"
        )
        if meta.note:
            print(f"      ↳ {meta.note}")
    if len(models) > 20:
        print(f"  …（其余 {len(models) - 20} 个已全部入库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
