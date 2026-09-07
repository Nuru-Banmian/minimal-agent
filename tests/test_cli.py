import os
import subprocess
import sys

import pytest


def run_cli(model_server, text, overrides=None):
    env = os.environ.copy()
    env.update(
        {
            "PYTHONUTF8": "1",
            "DASHSCOPE_API_KEY": "test-key",
            "LLM_MODEL": "qwen-plus",
            "LLM_BASE_URL": model_server.url,
            "LLM_TIMEOUT_SECONDS": "2",
        }
    )
    env.update(overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "minimal_agent"],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
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
