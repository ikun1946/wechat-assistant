"""LLM 调用引擎：支持多厂商（OpenAI 兼容 + Anthropic）/ 本地模型 / 思考等级。

关键能力：
- api_style = "openai"  → POST {base_url}/chat/completions（绝大多数厂商）
- api_style = "anthropic" → POST {base_url}/messages（Claude）

思考等级（llm.thinking_level）的落地方式按厂商而异，这里统一处理：
- "off"：能关就关（Qwen3 用 /no_think；智谱/百炼/方舟用 enable_thinking=false；Claude 不传 thinking）
- "low/medium/high"：OpenAI 传 reasoning_effort；Claude 传 thinking.budget_tokens；
  其它支持开关的厂商传 enable_thinking=true

安全约定：API Key 只从环境变量或本地 secrets.toml 读取，绝不写进 config.toml、绝不进日志。
"""

from __future__ import annotations

import json
import os
import urllib.request

from ..config import LLMConfig, load_secret_api_key
from ..providers import get_provider

# 思考预算（Claude thinking.budget_tokens）
_THINKING_BUDGET = {"low": 1_024, "medium": 4_096, "high": 16_384}

# 支持 enable_thinking 参数的厂商（OpenAI 兼容风格）
_ENABLE_THINKING_PROVIDERS = {"dashscope", "ark", "zhipu", "siliconflow", "moonshot", "minimax"}


class LLMError(Exception):
    """LLM 调用失败。"""


class LLMEngine:
    def __init__(self, config: LLMConfig):
        if not config.base_url or not config.model:
            raise LLMError("llm.base_url / llm.model 未配置")
        self._config = config
        self._provider = get_provider(config.provider)

    # ---------- 鉴权 ----------
    def _resolve_api_key(self) -> str | None:
        env_name = (self._config.api_key_env or "").strip()
        if env_name:
            value = os.environ.get(env_name, "").strip()
            if value:
                return value
            secret = load_secret_api_key()
            if secret:
                return secret
            raise LLMError(
                f"未找到 API Key：请设置环境变量 {env_name}，或在图形界面「模型」页填入 Key"
            )
        return load_secret_api_key()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self._resolve_api_key()
        if key:
            if self._config.api_style == "anthropic":
                headers["x-api-key"] = key
                headers["anthropic-version"] = "2023-06-01"
            else:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def _request_json(self, url: str, *, data: bytes | None = None, method: str = "GET"):
        request = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # 统一转成 LLMError 交给上层处理
            raise LLMError(f"请求失败（{url}）：{exc}") from exc

    # ---------- 思考等级 ----------
    def _apply_thinking(self, body: dict, system_prompt: str) -> str:
        """按厂商把思考等级写进请求体（必要时改写系统提示词）。返回（可能改写后的）系统提示词。"""
        level = self._config.thinking_level
        if level == "auto":
            return system_prompt
        provider_key = self._provider.key
        model = self._config.model.lower()

        if self._config.api_style == "anthropic":
            if level == "off":
                body.pop("thinking", None)
            else:
                body["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": _THINKING_BUDGET.get(level, 4_096),
                }
            return system_prompt

        # OpenAI 兼容
        if level == "off":
            if provider_key in _ENABLE_THINKING_PROVIDERS:
                body["enable_thinking"] = False
            if self._provider.local:
                # 本地服务（LM Studio / Ollama，走 llama.cpp 的 OpenAI 兼容层）关思考的标准写法。
                # `/no_think` 是 Qwen3 的老办法，对新版模型常常无效。
                # ⚠ 但这**不是万能的**：实测 qwen/qwen3.5-9b 在 LM Studio 上
                # `/no_think` 和 chat_template_kwargs 都关不掉思考 —— 思考型模型
                # 就是要先想完才吐字。碰到这种情况只能换模型或加大超时，
                # 详见 tools/probe_disable_thinking.py。
                body["chat_template_kwargs"] = {"enable_thinking": False}
            elif model.startswith("qwen3") or "qwen3" in model:
                # Qwen3 官方推荐：在提示词末尾加 /no_think 关闭思考
                if "/no_think" not in system_prompt:
                    system_prompt = (system_prompt + " /no_think").strip()
            return system_prompt

        if provider_key == "openai" or model.startswith(("gpt-5", "o1", "o3", "o4")):
            body["reasoning_effort"] = level
        elif provider_key in _ENABLE_THINKING_PROVIDERS:
            body["enable_thinking"] = True
        return system_prompt

    # ---------- 对外 ----------
    def list_models(self) -> list[str]:
        """获取服务端可用模型列表（OpenAI 兼容的 GET /models）。"""
        url = self._config.base_url.rstrip("/") + "/models"
        data = self._request_json(url)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise LLMError("模型列表格式异常（期望 OpenAI 兼容的 /models 响应）")
        models = [str(item.get("id", "")).strip() for item in items if isinstance(item, dict)]
        return [m for m in models if m]

    def test_chat(self, prompt: str = "你好") -> str:
        """连通性 + 生成能力自检。"""
        return self.generate(prompt)

    def generate(
        self,
        user_text: str,
        *,
        system_prompt: str | None = None,
        history: list[tuple[str, str]] | None = None,
    ) -> str:
        """生成一条回复。history 为 [(role, content), ...]，role 取 user/assistant。"""
        system = system_prompt if system_prompt is not None else self._config.system_prompt
        if self._config.api_style == "anthropic":
            return self._generate_anthropic(user_text, system, history or [])
        return self._generate_openai(user_text, system, history or [])

    # ---------- OpenAI 兼容 ----------
    def _generate_openai(self, user_text: str, system: str, history: list[tuple[str, str]]) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for role, content in history:
            if role in ("user", "assistant", "system"):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        max_tokens = self._effective_max_tokens()
        body: dict = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": max_tokens,
        }
        system = self._apply_thinking(body, system)
        if system and messages and messages[0]["role"] == "system":
            messages[0]["content"] = system

        url = self._config.base_url.rstrip("/") + "/chat/completions"
        data = self._request_json(url, data=json.dumps(body).encode("utf-8"), method="POST")
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"响应格式异常：{exc}") from exc
        if not isinstance(message, dict):
            raise LLMError("响应格式异常：message 不是对象")

        content = message.get("content")
        text = content.strip() if isinstance(content, str) else ""
        if text:
            return text

        # content 为空：思考型模型常见两种原因，给出可直接照做的提示
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        finished = str(data["choices"][0].get("finish_reason", ""))
        if reasoning:
            raise LLMError(
                f"模型只返回了思考内容、没有正文（思考 {len(str(reasoning))} 字，"
                f"finish_reason={finished or '未知'}）。"
                f"请把「最大输出」调大（建议 ≥1024），或把「思考等级」设为关闭"
            )
        raise LLMError(f"模型返回了空内容（finish_reason={finished or '未知'}）")

    def _effective_max_tokens(self) -> int:
        """思考型模型会先消耗 token 思考；预算太小会导致正文为空，这里兜个底。"""
        configured = max(1, int(self._config.max_tokens))
        if self._config.thinking_level == "off":
            return configured
        return max(configured, 1024)

    # ---------- Anthropic ----------
    def _generate_anthropic(self, user_text: str, system: str, history: list[tuple[str, str]]) -> str:
        messages: list[dict[str, str]] = []
        for role, content in history:
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})

        body: dict = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }
        if system:
            body["system"] = system
        self._apply_thinking(body, system)

        url = self._config.base_url.rstrip("/") + "/messages"
        data = self._request_json(url, data=json.dumps(body).encode("utf-8"), method="POST")
        try:
            blocks = data["content"]
        except (KeyError, TypeError) as exc:
            raise LLMError(f"响应格式异常：{exc}") from exc
        parts = [
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "".join(parts).strip()
        if not text:
            raise LLMError("模型返回了空内容")
        return text
