"""技能自学习器（SkillLearner）单元测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wxbot.brain.learned import LearnedStore
from wxbot.brain.learner import ConversationSample, LearnError, SkillLearner


def make_sample() -> ConversationSample:
    return ConversationSample(
        chat_name="张三",
        messages=(("them", "今天要加班吗"), ("me", "看情况，晚点说"), ("them", "好")),
    )


def fixed_generator(payload: str):
    def _generator(text, *, system_prompt, history):
        return payload

    return _generator


class SkillLearnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "learned.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_parse_plain_json(self):
        payload = json.dumps(
            [
                {
                    "type": "faq",
                    "scope": "global",
                    "keywords": ["加班"],
                    "title": "加班",
                    "content": "别人问加班就说到家再说",
                    "examples": ["今天要加班吗"],
                },
                {"type": "note", "scope": "张三", "title": "备注", "content": "张三是我同事"},
            ],
            ensure_ascii=False,
        )
        learner = SkillLearner(LearnedStore(self.path), fixed_generator(payload))
        report = learner.learn_from([make_sample()])
        self.assertEqual((report.added, report.duplicates, report.invalid), (2, 0, 0))
        self.assertEqual(report.total, 2)

        items = LearnedStore(self.path).items()
        self.assertEqual(items[0].keywords, ("加班",))
        self.assertEqual(items[1].scope, "张三")

    def test_parse_fenced_json(self):
        payload = (
            '```json\n[{"type": "style", "scope": "张三", "title": "风格", '
            '"content": "爱用～"}]\n```'
        )
        learner = SkillLearner(LearnedStore(self.path), fixed_generator(payload))
        report = learner.learn_from([make_sample()])
        self.assertEqual(report.added, 1)
        item = LearnedStore(self.path).items()[0]
        self.assertEqual(item.type, "style")
        self.assertEqual(item.scope, "global")  # style 强制全局

    def test_second_run_counts_duplicates(self):
        payload = json.dumps(
            [{"type": "style", "scope": "global", "title": "风格", "content": "爱用哈哈哈"}],
            ensure_ascii=False,
        )
        store = LearnedStore(self.path)
        learner = SkillLearner(store, fixed_generator(payload))
        learner.learn_from([make_sample()])
        report = learner.learn_from([make_sample()])
        self.assertEqual((report.added, report.duplicates), (0, 1))

    def test_invalid_items_skipped(self):
        payload = json.dumps(
            [
                {"type": "unknown", "content": "x"},
                {"type": "faq", "content": ""},
                {"type": "faq", "scope": "global", "title": "有效", "content": "有效内容"},
            ],
            ensure_ascii=False,
        )
        learner = SkillLearner(LearnedStore(self.path), fixed_generator(payload))
        report = learner.learn_from([make_sample()])
        self.assertEqual((report.added, report.invalid), (1, 2))

    def test_garbage_output_raises(self):
        learner = SkillLearner(LearnedStore(self.path), fixed_generator("抱歉，我无法总结。"))
        with self.assertRaises(LearnError):
            learner.learn_from([make_sample()])

    def test_empty_array_ok(self):
        learner = SkillLearner(LearnedStore(self.path), fixed_generator("[]"))
        report = learner.learn_from([make_sample()])
        self.assertEqual((report.added, report.total), (0, 0))

    def test_too_few_samples_raises(self):
        learner = SkillLearner(LearnedStore(self.path), fixed_generator("[]"))
        with self.assertRaises(LearnError):
            learner.learn_from(
                [ConversationSample(chat_name="张三", messages=(("them", "嗨"),))]
            )


if __name__ == "__main__":
    unittest.main()
