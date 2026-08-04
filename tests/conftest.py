from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

import pytest


FunctionResultBuilder = Callable[[str, dict], dict]


class _FunctionCallingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        request_payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        function = request_payload["tools"][0]["function"]
        user_content = request_payload["messages"][-1]["content"]
        if isinstance(user_content, list):
            text_part = next(item for item in user_content if item.get("type") == "text")
            user_content = text_part["text"]
        context = json.loads(user_content)
        arguments = self.server.result_builder(function["name"], context)  # type: ignore[attr-defined]
        response_payload = {
            "id": "chatcmpl-local-test",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call-local-test",
                        "type": "function",
                        "function": {
                            "name": function["name"],
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
        }
        encoded = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args) -> None:  # noqa: A003, ANN001
        return


@pytest.fixture
def function_call_server():
    active_servers: list[tuple[HTTPServer, threading.Thread]] = []

    def start(result_builder: FunctionResultBuilder) -> str:
        server = HTTPServer(("127.0.0.1", 0), _FunctionCallingHandler)
        server.result_builder = result_builder  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        active_servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}"

    yield start

    for server, thread in active_servers:
        server.shutdown()
        thread.join(timeout=5)
