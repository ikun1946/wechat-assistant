"""探测本机常见的本地模型服务（Ollama / LM Studio）。只读，不发送任何请求内容。"""

from __future__ import annotations

import json
import urllib.request

CANDIDATES = [
    ("Ollama", "http://127.0.0.1:11434/v1/models"),
    ("LM Studio", "http://127.0.0.1:1234/v1/models"),
]


def main() -> int:
    for name, url in CANDIDATES:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            items = data.get("data", []) if isinstance(data, dict) else []
            ids = [str(item.get("id", "")) for item in items if isinstance(item, dict)]
            print(f"[{name}] 可用：{url}")
            if ids:
                for model_id in ids[:15]:
                    print(f"    - {model_id}")
            else:
                print("    （服务已启动，但暂无已下载的模型）")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] 不可用：{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
