"""文本归一化小工具。

用途：会话名匹配。OCR 读出来的名字与用户手填的白名单常常只差全角/半角或空格，
例如「老王！」（全角）vs「老王!」（半角）。比较前统一归一化，避免"明明配了却匹配不上"。
"""

from __future__ import annotations

import re
import unicodedata


def normalize_name(name: str) -> str:
    """归一化会话名：全角转半角 + 去掉所有空白 + 去掉不影响辨识的标点差异。"""
    text = unicodedata.normalize("NFKC", name or "")
    text = re.sub(r"\s+", "", text)
    # 常见分隔符统一：冒号、括号等 NFKC 已处理大部分，这里只处理中文顿号/破折号
    text = text.replace("、", ",").replace("—", "-").replace("－", "-")
    return text.strip().lower()


def names_match(a: str, b: str) -> bool:
    """两个会话名是否指向同一个聊天。"""
    return bool(a) and bool(b) and normalize_name(a) == normalize_name(b)
