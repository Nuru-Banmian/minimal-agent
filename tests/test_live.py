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


def test_real_search_todo_sessions_and_clarification(tmp_path):
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://")
    database = tmp_path / "live-todos.sqlite3"

    def turn(session, prompt):
        # A fresh CLI process on every turn proves restoration, not in-memory continuity.
        result = subprocess.run(
            [
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
                "--search-provider",
                "mock",
            ],
            input=prompt + "\n/exit\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        assert result.returncode == 0 and not result.stderr, "真实 CLI 失败（省略服务错误）"
        events = [
            json.loads(line.split("trace: ", 1)[1])
            for line in result.stdout.splitlines()
            if "trace: " in line
        ]
        tools = [event for event in events if event["event"] == "tool"]
        answer = result.stdout.split("助手：")[-1].split("你：")[0].strip()
        print(
            json.dumps(
                {"session": session, "prompt": prompt, "answer": answer, "tools": tools},
                ensure_ascii=False,
            )
        )
        return answer, tools

    print(f"真实 search/todo CLI: {datetime.now(UTC).isoformat()} model={settings.model}")
    answer, tools = turn("1", "查上海的示例天气，帮我记一个带伞的待办")
    assert any(event["name"] == "search" and event["result"]["matches"] for event in tools)
    umbrella = next(
        event["result"]["item"]
        for event in tools
        if event["name"] == "todo" and event["result"]["outcome"] == "added"
    )
    assert "伞" in umbrella["content"]
    assert "模拟" in answer and any(word in answer for word in ["非实时", "不是实时", "并非实时"])
    assert "2026" in answer and "09" in answer
    answer, tools = turn(
        "2",
        "根据我提供的本周工作内容写周报，并记一个提交周报的待办。"
        "本周已完成登录页开发和三个缺陷修复，下周准备联调。",
    )
    report = next(
        event["result"]["item"]
        for event in tools
        if event["name"] == "todo" and event["result"]["outcome"] == "added"
    )
    assert "周报" in report["content"] and "登录" in answer and "联调" in answer
    _, tools = turn("1", "列出我的待办")
    assert next(event["result"]["items"] for event in tools if event["name"] == "todo") == [
        umbrella
    ]
    _, tools = turn("1", "把带伞那项完成")
    assert any(
        event["result"].get("outcome") == "completed"
        and event["result"]["item"]["id"] == umbrella["id"]
        for event in tools
    )
    _, tools = turn("2", "列出我的待办")
    assert next(event["result"]["items"] for event in tools if event["name"] == "todo") == [report]
    _, tools = turn("1", "再把带伞那项完成")
    assert tools and all(event["result"].get("outcome") != "completed" for event in tools)
    answer, tools = turn("3", "帮我完成待办")
    assert not any(
        event["name"] == "todo" and json.loads(event["arguments"])["action"] == "complete"
        for event in tools
    )
    assert any(word in answer for word in ["哪", "提供", "告诉", "没有", "暂无"])
    turn("3", "分别添加两个待办：提交周报、提交月报")
    answer, tools = turn("3", "把提交报告那项完成")
    assert not any(
        event["name"] == "todo" and json.loads(event["arguments"])["action"] == "complete"
        for event in tools
    )
    assert "周报" in answer and "月报" in answer


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
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "minimal_agent",
            "--db",
            ":memory:",
            "--search-provider",
            "mock",
        ],
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
            "--search-provider",
            "mock",
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
