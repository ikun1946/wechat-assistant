"""厂商注册表 + 模型元数据库。

两件事：
1) PROVIDERS —— 内置主流厂商预设（地址 / 鉴权方式 / 控制台链接 / Key 环境变量名）；
2) lookup_model_meta() —— 按厂商 + 模型名，自动推断该模型的元数据：
   上下文长度、支持的输入模态、思考等级能力、最大输出、当地是否支持。

元数据只是「自动填好的默认值」，用户可以在图形界面里逐模型改写。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# 输入模态
MODALITIES: tuple[str, ...] = ("text", "image", "audio", "video", "file")
MODALITY_LABELS = {
    "text": "文本",
    "image": "图片",
    "audio": "音频",
    "video": "视频",
    "file": "文件",
}

# 思考等级（auto=交给厂商默认；off=关闭思考）
THINKING_LEVELS: tuple[str, ...] = ("auto", "off", "low", "medium", "high")
THINKING_LABELS = {
    "auto": "自动（跟随模型默认）",
    "off": "关闭思考（最快）",
    "low": "低（思考量少）",
    "medium": "中",
    "high": "高（思考量大，最慢）",
}


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    api_style: str  # "openai" = /chat/completions；"anthropic" = /messages
    key_env: str
    console_url: str = ""
    local: bool = False
    note: str = ""


PROVIDERS: tuple[Provider, ...] = (
    # ---------- 国内主流 ----------
    Provider(
        key="deepseek",
        label="DeepSeek（深度求索）",
        base_url="https://api.deepseek.com/v1",
        api_style="openai",
        key_env="DEEPSEEK_API_KEY",
        console_url="https://platform.deepseek.com/api_keys",
        note="deepseek-chat 便宜好用；deepseek-reasoner 带思考链",
    ),
    Provider(
        key="moonshot",
        label="Moonshot Kimi（月之暗面）",
        base_url="https://api.moonshot.cn/v1",
        api_style="openai",
        key_env="MOONSHOT_API_KEY",
        console_url="https://platform.moonshot.cn/console/api-keys",
    ),
    Provider(
        key="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_style="openai",
        key_env="ZHIPU_API_KEY",
        console_url="https://open.bigmodel.cn/usercenter/apikeys",
    ),
    Provider(
        key="dashscope",
        label="通义千问（阿里云百炼）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_style="openai",
        key_env="DASHSCOPE_API_KEY",
        console_url="https://bailian.console.aliyun.com/",
    ),
    Provider(
        key="ark",
        label="豆包 · 火山方舟",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_style="openai",
        key_env="ARK_API_KEY",
        console_url="https://console.volcengine.com/ark",
        note="model 填接入点 ID（ep-xxxx）或模型 ID",
    ),
    Provider(
        key="minimax",
        label="MiniMax（稀宇科技）",
        base_url="https://api.minimaxi.com/v1",
        api_style="openai",
        key_env="MINIMAX_API_KEY",
        console_url="https://platform.minimaxi.com/user-center/basic-information/interface-key",
        note="海外账号用 https://api.minimax.io/v1",
    ),
    Provider(
        key="hunyuan",
        label="腾讯混元",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        api_style="openai",
        key_env="HUNYUAN_API_KEY",
        console_url="https://console.cloud.tencent.com/hunyuan/api-key",
    ),
    Provider(
        key="siliconflow",
        label="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        api_style="openai",
        key_env="SILICONFLOW_API_KEY",
        console_url="https://cloud.siliconflow.cn/account/ak",
        note="聚合平台，国内可直连多个开源模型",
    ),
    Provider(
        key="baichuan",
        label="百川智能",
        base_url="https://api.baichuan-ai.com/v1",
        api_style="openai",
        key_env="BAICHUAN_API_KEY",
        console_url="https://platform.baichuan-ai.com/console/apikey",
    ),
    Provider(
        key="lingyiwanwu",
        label="零一万物 Yi",
        base_url="https://api.lingyiwanwu.com/v1",
        api_style="openai",
        key_env="YI_API_KEY",
        console_url="https://platform.lingyiwanwu.com/apikeys",
    ),
    # ---------- 海外主流 ----------
    Provider(
        key="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        api_style="openai",
        key_env="OPENAI_API_KEY",
        console_url="https://platform.openai.com/api-keys",
        note="gpt-5 / o 系列支持思考等级（低/中/高）",
    ),
    Provider(
        key="anthropic",
        label="Anthropic Claude",
        base_url="https://api.anthropic.com/v1",
        api_style="anthropic",
        key_env="ANTHROPIC_API_KEY",
        console_url="https://console.anthropic.com/settings/keys",
        note="使用 /messages 接口（本程序已适配）",
    ),
    Provider(
        key="gemini",
        label="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_style="openai",
        key_env="GEMINI_API_KEY",
        console_url="https://aistudio.google.com/app/apikey",
        note="走官方 OpenAI 兼容端点",
    ),
    Provider(
        key="xai",
        label="xAI Grok",
        base_url="https://api.x.ai/v1",
        api_style="openai",
        key_env="XAI_API_KEY",
        console_url="https://console.x.ai/",
    ),
    Provider(
        key="groq",
        label="Groq（极速推理）",
        base_url="https://api.groq.com/openai/v1",
        api_style="openai",
        key_env="GROQ_API_KEY",
        console_url="https://console.groq.com/keys",
    ),
    Provider(
        key="openrouter",
        label="OpenRouter（聚合）",
        base_url="https://openrouter.ai/api/v1",
        api_style="openai",
        key_env="OPENROUTER_API_KEY",
        console_url="https://openrouter.ai/settings/keys",
        note="一个 Key 通吃数百个模型",
    ),
    # ---------- 本地 ----------
    Provider(
        key="lmstudio",
        label="LM Studio（本地）",
        base_url="http://127.0.0.1:1234/v1",
        api_style="openai",
        key_env="",
        local=True,
        note="需在 Developer 页启动本地服务",
    ),
    Provider(
        key="ollama",
        label="Ollama（本地）",
        base_url="http://127.0.0.1:11434/v1",
        api_style="openai",
        key_env="",
        local=True,
    ),
    # ---------- 兜底 ----------
    Provider(
        key="custom",
        label="自定义 / 其它兼容服务",
        base_url="",
        api_style="openai",
        key_env="",
        note="任何 OpenAI 兼容端点都可以填这里",
    ),
)

_PROVIDER_MAP = {p.key: p for p in PROVIDERS}


def get_provider(key: str) -> Provider:
    return _PROVIDER_MAP.get(key, _PROVIDER_MAP["custom"])


def all_providers() -> tuple[Provider, ...]:
    return PROVIDERS


# ---------------------------------------------------------------------------
# 模型元数据推断
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelMeta:
    context_length: int
    modalities: tuple[str, ...]
    thinking_levels: tuple[str, ...]  # 该模型支持的思考等级选项
    default_thinking: str
    max_output_tokens: int
    note: str = ""


_ALL_THINKING = ("auto", "off", "low", "medium", "high")
_NO_THINKING = ("auto", "off")

# 规则表：(匹配正则, 元数据) —— 自上而下，先命中先用
_RULES: tuple[tuple[str, ModelMeta], ...] = (
    # ---- OpenAI ----
    (r"^gpt-5", ModelMeta(400_000, ("text", "image"), _ALL_THINKING, "medium", 16_384, "支持思考等级")),
    (r"^gpt-4\.1", ModelMeta(1_000_000, ("text", "image"), _NO_THINKING, "auto", 16_384)),
    (r"^gpt-4o", ModelMeta(128_000, ("text", "image", "audio"), _NO_THINKING, "auto", 16_384)),
    (r"^o[1-9]", ModelMeta(200_000, ("text", "image"), _ALL_THINKING, "medium", 32_768, "推理模型")),
    (r"gpt-oss", ModelMeta(131_072, ("text",), _ALL_THINKING, "auto", 32_768, "开源推理模型")),
    # ---- Anthropic ----
    (r"^claude.*(opus|sonnet|haiku)", ModelMeta(200_000, ("text", "image"), _ALL_THINKING, "auto", 8_192, "支持思考预算")),
    # ---- Google ----
    (r"^gemini-2\.5|^gemini-3", ModelMeta(1_000_000, ("text", "image", "audio", "video"), _ALL_THINKING, "auto", 8_192)),
    (r"^gemini", ModelMeta(1_000_000, ("text", "image", "audio", "video"), _NO_THINKING, "auto", 8_192)),
    # ---- 中文模型 ----
    (r"^minicpm-v|minicpm.*vision", ModelMeta(32_768, ("text", "image"), _NO_THINKING, "auto", 4_096, "MiniCPM-V 是视觉模型，已按多模态预填")),
    (r"^minicpm", ModelMeta(32_768, ("text",), _NO_THINKING, "auto", 4_096)),
    (r"^qwen3|^qwen-3", ModelMeta(131_072, ("text",), ("auto", "off"), "off", 8_192, "默认开启思考，短回复建议关闭")),
    (r"^qwen2\.5|^qwen-2\.5", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^qwen.*(vl|omni)", ModelMeta(131_072, ("text", "image", "video"), _NO_THINKING, "auto", 8_192, "多模态")),
    (r"^qwen", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^glm-4\.[5-9]|^glm-5", ModelMeta(200_000, ("text",), _ALL_THINKING, "auto", 16_384, "支持思考开关")),
    (r"^glm-4v|^glm-4\.1v", ModelMeta(128_000, ("text", "image"), _NO_THINKING, "auto", 4_096)),
    (r"^glm", ModelMeta(128_000, ("text",), _NO_THINKING, "auto", 4_096)),
    (r"^deepseek-reasoner|^deepseek-r1", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 32_768, "自带思考链")),
    (r"^deepseek", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^kimi-k2|^kimi-thinking", ModelMeta(262_144, ("text",), _ALL_THINKING, "auto", 16_384)),
    (r"^kimi|^moonshot", ModelMeta(262_144, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^doubao.*(vision|vl)", ModelMeta(262_144, ("text", "image"), _ALL_THINKING, "auto", 16_384)),
    (r"^doubao|^ep-", ModelMeta(262_144, ("text",), _ALL_THINKING, "auto", 16_384)),
    (r"^minimax|^abab", ModelMeta(245_760, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^hunyuan.*(vision|vl)", ModelMeta(131_072, ("text", "image"), _NO_THINKING, "auto", 8_192)),
    (r"^hunyuan", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^yi-", ModelMeta(200_000, ("text",), _NO_THINKING, "auto", 4_096)),
    (r"^baichuan", ModelMeta(32_768, ("text",), _NO_THINKING, "auto", 4_096)),
    # ---- 海外开源 ----
    (r"^llama-4", ModelMeta(1_000_000, ("text", "image"), _NO_THINKING, "auto", 8_192)),
    (r"^llama-3", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 4_096)),
    (r"^gemma-3", ModelMeta(131_072, ("text", "image"), _NO_THINKING, "auto", 8_192)),
    (r"^gemma", ModelMeta(8_192, ("text",), _NO_THINKING, "auto", 4_096)),
    (r"^mistral|^mixtral|^ministral", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 8_192)),
    (r"^phi-4|^phi4", ModelMeta(131_072, ("text",), _NO_THINKING, "auto", 4_096)),
    (r"^grok", ModelMeta(256_000, ("text", "image"), _ALL_THINKING, "auto", 16_384)),
    # ---- 通用兜底 ----
    (r"vl|vision|omni", ModelMeta(32_768, ("text", "image"), _NO_THINKING, "auto", 4_096, "名称含视觉标识，已按多模态预填")),
    (r"reason|thinking|r1", ModelMeta(32_768, ("text",), _NO_THINKING, "auto", 8_192, "名称含推理标识")),
    (r".", ModelMeta(32_768, ("text",), _NO_THINKING, "auto", 4_096, "未收录模型，已按常见默认值预填")),
)


def _match_rule(name: str) -> ModelMeta | None:
    for pattern, meta in _RULES:
        if re.search(pattern, name):
            return meta
    return None


# 强视觉标识：这些是业界通行的命名约定，命中即可认为支持图片输入。
# 放在家族规则**之后**做兜底升级：家族规则里 `^llama-3`、`^gemma` 等会把
# `llama-3.2-vision` 这类视觉变体误判成纯文本（表尾那条通用规则因为前面已命中而永远走不到）。
_VISION_RE = re.compile(r"(^|[-_.])vl\b|vision|omni|llava|internvl|[-_]v[-_]\d")


def _upgrade_vision(meta: ModelMeta, name: str) -> ModelMeta:
    """家族规则判成纯文本、但名称带强视觉标识时，把 image 补回来。"""
    if "image" in meta.modalities or not _VISION_RE.search(name):
        return meta
    return replace(meta, modalities=("text", "image"))


def lookup_model_meta(provider_key: str, model_id: str) -> ModelMeta:
    """按厂商 + 模型名推断元数据（本地模型的上下文固定给 8K 保守值）。"""
    name = (model_id or "").strip().lower()
    provider = get_provider(provider_key)
    matched = _match_rule(name)
    if matched is not None:
        matched = _upgrade_vision(matched, name)

    if provider.local:
        # 本地模型的上下文由加载设置决定，固定 8K；
        # 但**模态 / 思考等级仍要走规则表** —— 本地跑视觉模型（minicpm-v、qwen2-vl、llava…）
        # 很常见，早先在这里直接 return ("text",) 把整张规则表短路掉了，
        # 结果本地视觉模型一律被勾成"不支持图片"。
        if matched is None:
            return ModelMeta(
                8_192, ("text",), _NO_THINKING, "auto", 2_048, "本地模型，上下文以加载设置为准"
            )
        note = f"{matched.note}；本地模型上下文按 8K 保守预填" if matched.note else "本地模型上下文按 8K 保守预填"
        return ModelMeta(
            8_192,
            matched.modalities,
            matched.thinking_levels,
            matched.default_thinking,
            matched.max_output_tokens,
            note,
        )

    if matched is not None:
        return matched
    return ModelMeta(32_768, ("text",), _NO_THINKING, "auto", 4_096)


def meta_to_dict(meta: ModelMeta) -> dict:
    return {
        "context_length": meta.context_length,
        "modalities": list(meta.modalities),
        "thinking_levels": list(meta.thinking_levels),
        "default_thinking": meta.default_thinking,
        "max_output_tokens": meta.max_output_tokens,
        "note": meta.note,
    }
