"""Run a real CLI against a scripted loopback model; no external API or keys."""

import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from threading import Thread


def main():
    replies = Queue()
    replies.put((429, {}))
    replies.put((200, {"role": "assistant", "content": "失败后已恢复，可以继续输入。"}))
    for number in range(2):
        replies.put(
            (
                200,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"bad-{number}",
                            "type": "function",
                            "function": {"name": "missing", "arguments": "{}"},
                        }
                    ],
                },
            )
        )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            status, message = replies.get(timeout=3)
            payload = {
                "choices": [
                    {
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                        "message": message,
                    }
                ]
            }
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            env = os.environ.copy()
            # Isolate the demo from local provider and memory settings.
            for key in list(env):
                if key.startswith("MEMORY_"):
                    del env[key]
            env.update(
                PYTHONUTF8="1",
                DASHSCOPE_API_KEY="offline-placeholder",
                LLM_MODEL="scripted-offline",
                LLM_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                LLM_TIMEOUT_SECONDS="2",
                SEARCH_PROVIDER="mock",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "minimal_agent",
                    "--db",
                    str(Path(directory) / "demo.sqlite3"),
                    "--max-steps",
                    "2",
                    "--trace-file",
                    str(trace),
                ],
                input="故障注入\n继续\n达到上限\n/exit\n",
                text=True,
                encoding="utf-8",
                capture_output=True,
                env=env,
                cwd=directory,
                timeout=15,
            )
            print("离线演示：真实 CLI + 回环 HTTP 脚本化模型；无真实 API。")
            print("输入：故障注入 / 继续 / 达到上限 / exit")
            print(result.stdout)
            print(result.stderr)
            events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
            stops = [(e["reason"], e["actual_requests"]) for e in events if e["event"] == "stop"]
            assert result.returncode == 0 and stops == [
                ("model_error", 1),
                ("final_answer", 1),
                ("step_limit", 2),
            ], stops
            assert replies.empty()
            print("已验证：限流失败请求 1 次；下一轮恢复 1 次；工具纠错达到上限 2 次。")
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


if __name__ == "__main__":
    main()
