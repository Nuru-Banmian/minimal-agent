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

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_API") != "1", reason="真实 API 验证未显式开启"
)


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
        [sys.executable, "-X", "utf8", "-m", "minimal_agent"],
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
