"""Explicitly opt in; this test never substitutes a scripted model for the real API."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime

import httpx
import pytest

from minimal_agent.client import Message, ModelClient
from minimal_agent.config import Settings
from minimal_agent.runtime import Runtime

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_API") != "1", reason="真实 API 验证未显式开启"
)


def test_real_calculator_loop_and_followup():
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://")
    events = []
    with ModelClient(settings) as client:
        runtime = Runtime(client, trace=events.append)
        first = runtime.run("用计算器计算 (12+8)*3")
        second = runtime.run("结果再除以 4")
    tools = [e for e in events if e["event"] == "tool"]
    assert [(e["turn"], e.get("result")) for e in tools] == [(1, 20), (1, 60), (2, 15)]
    assert all(e["status"] == "ok" and e["name"] == "calculator" for e in tools)
    assert "60" in first and "15" in second
    print(f"真实 Runtime: {datetime.now(UTC).isoformat()} model={settings.model}")
    for event in events:
        # Omit model prose; record execution facts only, never settings or HTTP headers.
        if event["event"] != "action":
            print(json.dumps(event, ensure_ascii=False))


def test_real_api_remembers_name():
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://"), "真实验收要求配置 HTTPS 模型服务"
    messages: list[Message] = [
        {"role": "system", "content": "请用中文简短回答。"},
        {"role": "user", "content": "我叫小林"},
    ]
    with ModelClient(settings) as client:
        first = client.complete(messages)
        messages.extend(
            [
                {"role": "assistant", "content": first},
                {"role": "user", "content": "我叫什么？只回答我的名字。"},
            ]
        )
        second = client.complete(messages)
    assert "小林" in second, "真实模型未正确回答名字（不输出原始服务响应）"
    print(f"真实 API: {datetime.now(UTC).isoformat()} model={settings.model}; 两轮成功，名字匹配")


def test_real_cli_remembers_name():
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "minimal_agent", "--db", ":memory:"],
        input="我叫小林\n我叫什么？只回答我的名字。\n/exit\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == 0, "真实 CLI 未正常退出"
    assert not result.stderr, "真实 CLI 报告请求或配置失败（省略原始输出）"
    answers = result.stdout.split("助手：")[1:]
    assert len(answers) == 2, "真实 CLI 未返回两轮回答"
    assert "小林" in answers[1], "真实 CLI 追问未正确返回名字"
    print("真实 CLI: 两轮回答成功，追问名字匹配，正常退出")


def test_real_cli_sessions_resume(tmp_path):
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://")
    database = tmp_path / "live.sqlite3"
    for session, name, a, expected in [("1", "小林", 12, 20), ("2", "小王", 30, 38)]:
        command = [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "minimal_agent",
            "--db",
            str(database),
            "--user-id",
            "live",
            "--session-id",
            session,
        ]
        for prompt, result_number in [
            (f"我叫{name}，请记住我的名字，并用计算器计算 {a}+8。", expected),
            ("我叫什么？把上次计算的结果再除以2，回答名字和结果。", expected // 2),
        ]:
            result = subprocess.run(
                command,
                input=prompt + "\n/exit\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=120,
            )
            assert result.returncode == 0 and not result.stderr, "真实 CLI 失败（省略原始输出）"
            answer = result.stdout.split("助手：")[-1]
            assert str(result_number) in answer, "真实计算未匹配结果"
            if result_number != expected:
                assert name in answer, "真实重启追问未匹配名字"
            assert f'"result": {result_number}' in result.stdout, "未观察到真实计算结果"
    print(
        f"真实 CLI session 重启: {datetime.now(UTC).isoformat()} model={settings.model}; "
        "session 1 小林 20→10；session 2 小王 38→19；四个进程均正常退出"
    )


def test_real_api_supports_function_calling():
    """Probe native tool-call support only; no tool execution or runtime is implemented here."""
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://"), "真实验收要求配置 HTTPS 模型服务"
    try:
        with httpx.Client(timeout=settings.timeout_seconds, trust_env=False) as http:
            response = http.post(
                f"{settings.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json={
                    "model": settings.model,
                    "messages": [{"role": "user", "content": "请调用 echo_name，name 为小林。"}],
                    "stream": False,
                    "enable_thinking": False,
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "echo_name",
                                "description": "返回给定姓名，仅用于协议验证。",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                    },
                                    "required": ["name"],
                                    "additionalProperties": False,
                                },
                            },
                        }
                    ],
                    "tool_choice": {"type": "function", "function": {"name": "echo_name"}},
                },
            )
    except httpx.HTTPError:
        pytest.fail("Function Calling 请求失败（省略原始服务错误）", pytrace=False)
    assert response.status_code == 200, "Function Calling 请求未成功（省略原始响应）"
    try:
        choice = response.json()["choices"][0]
        call = choice["message"]["tool_calls"][0]
        if choice.get("finish_reason") in {"stop", "tool_calls", "length", "content_filter"}:
            print(f"Function Calling finish_reason={choice['finish_reason']}")
        valid = (
            # Qwen forced calls can finish with "stop" while still returning valid tool_calls.
            choice["finish_reason"] in {"stop", "tool_calls"}
            and call["type"] == "function"
            and isinstance(call["id"], str)
            and bool(call["id"])
            and call["function"]["name"] == "echo_name"
            and json.loads(call["function"]["arguments"]) == {"name": "小林"}
        )
    except (ValueError, KeyError, IndexError, TypeError):
        valid = False
    assert valid, "Function Calling 返回内容未通过协议检查（省略原始响应）"
    print(f"真实 Function Calling: model={settings.model}; 调用 ID、函数名、JSON 参数验证通过")
