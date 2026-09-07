import json
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue
from threading import Thread
from typing import Any

import pytest


class ModelServer:
    """Scripted external model over real loopback HTTP; never calls a real model."""

    def __init__(self) -> None:
        self.replies: Queue[tuple[int, Any]] = Queue()
        self.requests: Queue[dict[str, Any]] = Queue()
        self.url = ""
        self.delay = 0.0

    def answer(self, content: str) -> None:
        self.replies.put(
            (
                200,
                {
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )
        )


@pytest.fixture
def model_server() -> Iterator[ModelServer]:
    model = ModelServer()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            model.requests.put(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(body),
                }
            )
            status, payload = model.replies.get(timeout=3)
            time.sleep(model.delay)
            encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The timeout test deliberately closes the connection before the reply.

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    model.url = f"http://127.0.0.1:{server.server_port}/compatible-mode/v1"
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield model
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
