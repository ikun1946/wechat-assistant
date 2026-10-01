"""LLM 引擎端到端冒烟：起一个本地假 OpenAI 兼容服务，验证 list_models / generate 全链路。

只在本机回环地址起临时服务，用于测试代码路径，不访问外网。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wxbot.brain.llm import LLMEngine
from wxbot.config import LLMConfig

PORT = 8099


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 安静输出
        return

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._send(
                {
                    "object": "list",
                    "data": [{"id": "mock-model-8b"}, {"id": "mock-model-14b"}],
                }
            )
        else:
            self.send_error(404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}
        if self.path.rstrip("/") == "/v1/chat/completions":
            messages = payload.get("messages", [])
            user = next(
                (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            self._send(
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": f"mock回复(收到:{user[:20]})"}}
                    ]
                }
            )
        else:
            self.send_error(404)


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        engine = LLMEngine(
            LLMConfig(base_url=f"http://127.0.0.1:{PORT}/v1", model="mock-model-8b", timeout_sec=5)
        )
        models = engine.list_models()
        print("list_models ->", models)
        assert models == ["mock-model-8b", "mock-model-14b"], models

        text = engine.generate(
            "你好",
            system_prompt="你是测试助手",
            history=[("user", "上一条"), ("assistant", "哈喽")],
        )
        print("generate ->", text)
        assert text.startswith("mock回复"), text
        print("LLM mock end-to-end OK")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
