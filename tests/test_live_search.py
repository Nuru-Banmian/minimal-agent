"""Opt-in real CLI + model + Tavily; no mocked search results."""

import json
import os
import subprocess
import sys

import pytest

from minimal_agent.config import Settings


@pytest.mark.skipif(os.environ.get("RUN_LIVE_SEARCH") != "1", reason="真实联网搜索未显式开启")
def test_real_cli_web_search_and_todo():
    settings = Settings.from_env()
    if not os.environ.get("TAVILY_API_KEY", "").strip():
        pytest.skip("未配置 TAVILY_API_KEY")
    assert settings.base_url.startswith("https://")
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
            "tavily",
        ],
        input="搜索 Python 官方文档并添加一个阅读文档的待办，回答附来源链接。\n/exit\n",
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
    search = next(event for event in tools if event["name"] == "search")
    assert search["status"] == "ok" and search["result"]["mock"] is False
    assert search["result"]["matches"]
    assert any(event["name"] == "todo" and event["result"]["outcome"] == "added" for event in tools)
    answer = result.stdout.split("助手：")[-1]
    assert any(row["source"] in answer for row in search["result"]["matches"])
    print(f"真实 CLI / {settings.model} / Tavily：搜索有结果、答案引用来源、待办已写入。")
