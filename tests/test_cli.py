import os
import subprocess
import sys
from contextlib import contextmanager
from queue import Queue
from threading import Thread

import pytest


def run_cli(model_server, text, overrides=None, cwd=None, args=()):
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUTF8": "1",
            "DASHSCOPE_API_KEY": "test-key",
            "LLM_MODEL": "qwen-plus",
            "LLM_BASE_URL": model_server.url,
            "LLM_TIMEOUT_SECONDS": "2",
            "SEARCH_PROVIDER": "mock",
        }
    )
    for name, value in (overrides or {}).items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return subprocess.run(
        [sys.executable, "-m", "minimal_agent", "--db", ":memory:", *args],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
        timeout=10,
    )


def test_cli_chat_followup_blank_and_exit(model_server):
    model_server.answer("你好，小林！")
    model_server.answer("你叫小林。")
    result = run_cli(model_server, "\n我叫小林\n我叫什么\n/exit\n不应发送\n")
    assert result.returncode == 0
    assert "助手：你好，小林！" in result.stdout
    assert "助手：你叫小林。" in result.stdout
    assert "再见" in result.stdout
    assert result.stderr == ""
    first = model_server.requests.get_nowait()["body"]["messages"]
    second = model_server.requests.get_nowait()["body"]["messages"]
    assert first[0]["role"] == "system"
    assert first[1:] == [{"role": "user", "content": "我叫小林"}]
    assert second == [
        *first,
        {"role": "assistant", "content": "你好，小林！"},
        {"role": "user", "content": "我叫什么"},
    ]
    assert model_server.requests.empty()


@pytest.mark.parametrize("text", ["", "\n \n", "/quit\n", " /EXIT \n"])
def test_cli_clean_exit_without_requests(model_server, text):
    result = run_cli(model_server, text)
    assert result.returncode == 0
    assert "再见" in result.stdout
    assert result.stderr == ""
    assert model_server.requests.empty()


@pytest.mark.parametrize(
    ("name", "value", "hint"),
    [
        ("DASHSCOPE_API_KEY", "", "DASHSCOPE_API_KEY"),
        ("LLM_MODEL", " ", "LLM_MODEL"),
        ("LLM_BASE_URL", "", "LLM_BASE_URL"),
        ("LLM_BASE_URL", "not-a-url", "LLM_BASE_URL"),
        ("LLM_BASE_URL", "https://example.com:bad/v1", "LLM_BASE_URL"),
        ("LLM_BASE_URL", "https://{WorkspaceId}.example.com/v1", "LLM_BASE_URL"),
        ("LLM_BASE_URL", "https://user:secret@example.com/v1", "LLM_BASE_URL"),
        ("LLM_BASE_URL", "https://example.com/v1?key=secret", "LLM_BASE_URL"),
        ("DASHSCOPE_API_KEY", "密钥占位符", "DASHSCOPE_API_KEY"),
        ("LLM_TIMEOUT_SECONDS", "oops", "LLM_TIMEOUT_SECONDS"),
        ("LLM_TIMEOUT_SECONDS", "0", "LLM_TIMEOUT_SECONDS"),
        ("LLM_TIMEOUT_SECONDS", "-1", "LLM_TIMEOUT_SECONDS"),
        ("LLM_TIMEOUT_SECONDS", "nan", "LLM_TIMEOUT_SECONDS"),
        ("LLM_TIMEOUT_SECONDS", "inf", "LLM_TIMEOUT_SECONDS"),
    ],
)
def test_cli_configuration_errors_are_clear(model_server, name, value, hint):
    result = run_cli(model_server, "", {name: value})
    assert result.returncode == 2
    assert hint in result.stderr
    assert "Traceback" not in result.stderr
    assert "secret" not in result.stderr
    assert model_server.requests.empty()


@pytest.mark.parametrize("environment_key", [None, "environment-key"])
def test_cli_loads_local_dotenv_with_environment_priority(model_server, tmp_path, environment_key):
    (tmp_path / ".env").write_text(
        f'LLM_MODEL=qwen-plus\nLLM_BASE_URL="{model_server.url}"\nDASHSCOPE_API_KEY="file-key"\n',
        encoding="utf-8-sig",
    )
    model_server.answer("配置已加载")
    result = run_cli(
        model_server,
        "你好\n/exit\n",
        {
            "LLM_MODEL": None,
            "LLM_BASE_URL": None,
            "DASHSCOPE_API_KEY": environment_key,
        },
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "助手：配置已加载" in result.stdout
    assert result.stderr == ""
    request = model_server.requests.get_nowait()
    assert request["authorization"] == f"Bearer {environment_key or 'file-key'}"
    assert model_server.requests.empty()


def test_cli_failure_does_not_enter_history_and_chat_can_continue(model_server):
    model_server.answer("你好，小林！")
    model_server.replies.put((401, {"error": {"message": "PRIVATE test-key"}}))
    model_server.answer("你叫小林。")
    result = run_cli(model_server, "我叫小林\n失败输入\n我叫什么\n/exit\n")
    assert result.returncode == 0
    assert "鉴权失败" in result.stderr
    assert "Traceback" not in result.stderr
    assert "PRIVATE" not in result.stderr
    assert "test-key" not in result.stderr
    assert "助手：你叫小林。" in result.stdout
    first = model_server.requests.get_nowait()["body"]["messages"]
    model_server.requests.get_nowait()
    third = model_server.requests.get_nowait()["body"]["messages"]
    assert third == [
        *first,
        {"role": "assistant", "content": "你好，小林！"},
        {"role": "user", "content": "我叫什么"},
    ]


def test_cli_timeout_is_not_an_assistant_answer(model_server):
    model_server.delay = 0.15
    model_server.answer("太晚的回答")
    result = run_cli(model_server, "你好\n/exit\n", {"LLM_TIMEOUT_SECONDS": "0.02"})
    assert result.returncode == 0
    assert "超时" in result.stderr
    assert "助手：" not in result.stdout
    assert "Traceback" not in result.stderr


def test_cli_calculator_loop_and_trace(model_server):
    model_server.replies.put(
        (
            200,
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "先相加",
                            "tool_calls": [
                                {
                                    "id": "cli-call",
                                    "type": "function",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"operation":"add","a":12,"b":8}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )
    )
    model_server.answer("20")
    result = run_cli(model_server, "用计算器计算 12+8\n/exit\n")
    assert result.returncode == 0
    assert result.stderr == ""
    assert "助手：20" in result.stdout
    assert '"tool_call_id": "cli-call"' in result.stdout
    assert '"result": 20' in result.stdout
    assert '"reason": "final_answer"' in result.stdout


def test_cli_displays_identity_and_restores_session(model_server, tmp_path):
    args = ["--db", str(tmp_path / "chat.sqlite3"), "--user-id", "小林", "--session-id", "1"]
    model_server.answer("记住了")
    first = run_cli(model_server, "我的颜色是蓝色\n/exit\n", args=args)
    assert first.returncode == 0
    assert "user_id=小林" in first.stdout and "session_id=1" in first.stdout
    model_server.answer("蓝色")
    second = run_cli(model_server, "我的颜色？\n/exit\n", args=args)
    assert second.returncode == 0
    assert "助手：蓝色" in second.stdout
    model_server.requests.get_nowait()
    assert model_server.requests.get_nowait()["body"]["messages"][1:] == [
        {"role": "user", "content": "我的颜色是蓝色"},
        {"role": "assistant", "content": "记住了"},
        {"role": "user", "content": "我的颜色？"},
    ]


@contextmanager
def interactive_cli(model_server, database, session):
    env = os.environ.copy()
    env.update(
        DASHSCOPE_API_KEY="test-key",
        LLM_MODEL="qwen-plus",
        LLM_BASE_URL=model_server.url,
        SEARCH_PROVIDER="mock",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-X",
            "utf8",
            "-m",
            "minimal_agent",
            "--db",
            str(database),
            "--user-id",
            "u",
            "--session-id",
            session,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    lines = Queue()
    reader = Thread(target=lambda: [lines.put(line) for line in process.stdout], daemon=True)
    reader.start()

    def wait_for(fragment):
        while fragment not in lines.get(timeout=10):
            pass

    def send(text):
        process.stdin.write(text + "\n")
        process.stdin.flush()

    try:
        wait_for("当前会话")
        yield process, send, wait_for
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()


@pytest.mark.parametrize("kill_owner", [False, True])
def test_two_cli_processes_alternate_conflict_and_recover(model_server, tmp_path, kill_owner):
    database = tmp_path / "chat.sqlite3"
    with interactive_cli(model_server, database, "1") as (first, send1, wait1):
        with interactive_cli(model_server, database, "2") as (_, send2, wait2):
            for send, wait, fact in [(send1, wait1, "小林"), (send2, wait2, "小王")]:
                model_server.answer(f"你好，{fact}")
                send(f"我叫{fact}")
                wait(f"助手：你好，{fact}")
                assert model_server.requests.get(timeout=5)["body"]["messages"][1:] == [
                    {"role": "user", "content": f"我叫{fact}"}
                ]
            conflict = run_cli(
                model_server,
                "不应发送\n",
                args=["--db", str(database), "--user-id", "u", "--session-id", "1"],
            )
            assert conflict.returncode == 2
            assert "占用" in conflict.stderr and "Traceback" not in conflict.stderr
            assert model_server.requests.empty()
            model_server.answer("小林")
            send1("我叫什么")
            wait1("助手：小林")
            history = model_server.requests.get(timeout=5)["body"]["messages"]
            assert history[1:] == [
                {"role": "user", "content": "我叫小林"},
                {"role": "assistant", "content": "你好，小林"},
                {"role": "user", "content": "我叫什么"},
            ]
            if kill_owner:
                first.kill()
            else:
                send1("/exit")
            first.wait(timeout=5)
            model_server.answer("小林")
            restored = run_cli(
                model_server,
                "再说一次\n/exit\n",
                args=["--db", str(database), "--user-id", "u", "--session-id", "1"],
            )
            assert restored.returncode == 0 and not restored.stderr
            assert model_server.requests.get(timeout=5)["body"]["messages"] == [
                *history,
                {"role": "assistant", "content": "小林"},
                {"role": "user", "content": "再说一次"},
            ]
            send2("/exit")
            wait2("再见")


@pytest.mark.parametrize("args", [["--user-id", " "], ["--session-id", ""]])
def test_cli_rejects_empty_identity(model_server, args):
    result = run_cli(model_server, "", args=args)
    assert result.returncode == 2
    assert "不能为空" in result.stderr and "Traceback" not in result.stderr


def test_cli_database_open_failure_is_clear(model_server, tmp_path):
    result = run_cli(model_server, "", args=["--db", str(tmp_path / "missing" / "chat.sqlite3")])
    assert result.returncode == 2
    assert "无法打开" in result.stderr and "Traceback" not in result.stderr
