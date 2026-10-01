"""厂商注册表与模型元数据库测试。"""

from __future__ import annotations

import unittest

from wxbot.providers import (
    MODALITIES,
    THINKING_LEVELS,
    all_providers,
    get_provider,
    lookup_model_meta,
)


class ProviderRegistryTests(unittest.TestCase):
    def test_has_many_providers(self):
        providers = all_providers()
        self.assertGreaterEqual(len(providers), 15)
        keys = [p.key for p in providers]
        self.assertEqual(len(keys), len(set(keys)), "厂商 key 不能重复")

    def test_expected_providers_present(self):
        keys = {p.key for p in all_providers()}
        for expected in (
            "openai", "anthropic", "gemini", "deepseek", "moonshot", "zhipu",
            "dashscope", "ark", "minimax", "siliconflow", "openrouter",
            "lmstudio", "ollama", "custom",
        ):
            self.assertIn(expected, keys)

    def test_local_flags_and_env(self):
        self.assertTrue(get_provider("lmstudio").local)
        self.assertTrue(get_provider("ollama").local)
        self.assertFalse(get_provider("deepseek").local)
        self.assertEqual(get_provider("deepseek").key_env, "DEEPSEEK_API_KEY")
        self.assertEqual(get_provider("anthropic").api_style, "anthropic")
        self.assertEqual(get_provider("openai").api_style, "openai")

    def test_unknown_provider_falls_back_to_custom(self):
        self.assertEqual(get_provider("不存在的厂商").key, "custom")


class ModelMetaTests(unittest.TestCase):
    def test_qwen3_thinking_can_be_disabled(self):
        meta = lookup_model_meta("lmstudio", "Qwen3-8B")
        self.assertIn("off", meta.thinking_levels)

    def test_gpt5_supports_reasoning_effort(self):
        meta = lookup_model_meta("openai", "gpt-5-mini")
        self.assertIn("low", meta.thinking_levels)
        self.assertIn("high", meta.thinking_levels)

    def test_vision_name_gets_image_modality(self):
        meta = lookup_model_meta("custom", "some-vl-model")
        self.assertIn("image", meta.modalities)

    def test_gemini_multimodal(self):
        meta = lookup_model_meta("gemini", "gemini-2.5-flash")
        for modality in ("text", "image", "audio", "video"):
            self.assertIn(modality, meta.modalities)

    def test_claude_context(self):
        meta = lookup_model_meta("anthropic", "claude-sonnet-4-5")
        self.assertGreaterEqual(meta.context_length, 200_000)

    def test_local_model_conservative_default(self):
        meta = lookup_model_meta("lmstudio", "某个没收录的模型")
        self.assertLessEqual(meta.context_length, 32_768)

    def test_all_meta_values_are_valid(self):
        samples = [
            ("openai", "gpt-4o"),
            ("deepseek", "deepseek-chat"),
            ("zhipu", "glm-4.6"),
            ("ark", "doubao-pro-32k"),
            ("ollama", "llama3.2:3b"),
            ("custom", "随便什么模型"),
        ]
        for provider, model in samples:
            meta = lookup_model_meta(provider, model)
            self.assertGreater(meta.context_length, 0)
            self.assertTrue(set(meta.modalities) <= set(MODALITIES), model)
            self.assertTrue(set(meta.thinking_levels) <= set(THINKING_LEVELS), model)
            self.assertIn(meta.default_thinking, meta.thinking_levels, model)
            self.assertGreater(meta.max_output_tokens, 0)

    def test_lookup_is_case_insensitive(self):
        upper = lookup_model_meta("openai", "GPT-5")
        lower = lookup_model_meta("openai", "gpt-5")
        self.assertEqual(upper.context_length, lower.context_length)


class LocalModelMetaTests(unittest.TestCase):
    """本地模型（LM Studio / Ollama）也必须走名称规则表。

    回归背景：早先 `lookup_model_meta` 在 `provider.local` 分支里直接
    `return ModelMeta(..., ("text",), ...)`，把整张规则表短路了 ——
    本地视觉模型（minicpm-v、qwen2-vl、llava…）全被判成"不支持图片"。
    """

    def test_local_vision_models_keep_image_modality(self):
        for model in ("minicpm-v-4.6", "MiniCPM-V-4_5", "qwen2-vl-7b", "llama-3.2-vision"):
            with self.subTest(model=model):
                meta = lookup_model_meta("lmstudio", model)
                self.assertIn("image", meta.modalities, model)
                self.assertIn("text", meta.modalities, model)

    def test_ollama_vision_model_also_detected(self):
        self.assertIn("image", lookup_model_meta("ollama", "minicpm-v:latest").modalities)

    def test_local_plain_text_model_stays_text_only(self):
        for model in ("gemma-4-e2b", "qwen3-8b", "某个没收录的模型"):
            with self.subTest(model=model):
                meta = lookup_model_meta("lmstudio", model)
                self.assertEqual(meta.modalities, ("text",), model)

    def test_local_context_stays_conservative(self):
        """即使名称规则命中，云端的大上下文也不能套到本地模型上。"""
        for model in ("minicpm-v-4.6", "gpt-5", "claude-sonnet-4-5", "随便什么"):
            with self.subTest(model=model):
                self.assertEqual(lookup_model_meta("lmstudio", model).context_length, 8_192)

    def test_local_respects_thinking_defaults(self):
        """规则表里的思考等级默认值对本地模型同样生效。"""
        self.assertEqual(lookup_model_meta("lmstudio", "Qwen3-8B").default_thinking, "off")

    def test_local_meta_note_explains_context_choice(self):
        self.assertIn("本地模型", lookup_model_meta("lmstudio", "minicpm-v-4.6").note)


if __name__ == "__main__":
    unittest.main()
