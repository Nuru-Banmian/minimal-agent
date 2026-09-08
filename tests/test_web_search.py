import json

import httpx
import pytest
from test_cli import run_cli
from test_runtime import reply
from test_search_todo import tool_call, tool_turn

from minimal_agent.client import ModelClient
from minimal_agent.config import Settings
from minimal_agent.runtime import Runtime
from minimal_agent.search import TavilySearch


def test_runtime_uses_web_results_before_adding_todo(model_server):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Python documentation",
                        "url": "https://docs.python.org/3/",
                        "content": "Python documentation and tutorial.",
                    }
                ]
            },
        )

    reply(model_server, [tool_call("search", query="Python documentation")])
    reply(model_server, [tool_call("todo", action="add", content="阅读 Python 教程")])
    model_server.answer("找到 Python 文档：https://docs.python.org/3/，已添加阅读待办。")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(
            client,
            search_tool=TavilySearch("test-search-key", transport=httpx.MockTransport(handle)),
        ) as runtime:
            runtime.run("搜索 Python 文档并记一个阅读待办")
    assert requests[0].url == "https://api.tavily.com/search"
    assert requests[0].headers["authorization"] == "Bearer test-search-key"
    assert json.loads(requests[0].content)["include_answer"] is False
    model_server.requests.get_nowait()
    result = json.loads(model_server.requests.get_nowait()["body"]["messages"][-1]["content"])
    assert result["status"] == "ok"
    assert result["result"]["mock"] is False
    assert result["result"]["matches"][0]["source"] == "https://docs.python.org/3/"
    assert result["result"]["matches"][0]["content"] == "Python documentation and tutorial."
    assert "test-search-key" not in json.dumps(result)


@pytest.mark.parametrize(
    "failure,expected",
    [
        (401, "search_authentication_failed"),
        (429, "search_rate_limited"),
        (432, "search_quota_exceeded"),
        (500, "search_unavailable"),
        ("timeout", "search_timeout"),
        ("connection", "search_unavailable"),
        ("malformed", "search_invalid_response"),
    ],
)
def test_search_failure_is_safe_tool_error_and_next_turn_works(model_server, failure, expected):
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-test-key")
        if failure == "connection":
            raise httpx.ConnectError("secret-test-key")
        if failure == "malformed":
            return httpx.Response(200, json={"unexpected": "secret-test-key"})
        return httpx.Response(failure, text="secret-test-key")

    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(
            client,
            search_tool=TavilySearch("secret-test-key", transport=httpx.MockTransport(handle)),
        ) as runtime:
            event = tool_turn(model_server, runtime, "search", query="test")
            assert event["status"] == "error" and event["error"] == expected
            assert "secret-test-key" not in json.dumps(event)
            assert tool_turn(model_server, runtime, "todo", action="list")["result"]["items"] == []


def test_cli_requires_search_key_without_mock_fallback(model_server):
    result = run_cli(
        model_server,
        "/exit\n",
        overrides={"TAVILY_API_KEY": ""},
        args=("--search-provider", "tavily"),
    )
    assert result.returncode == 2
    assert "TAVILY_API_KEY" in result.stderr
    assert model_server.requests.empty()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"results": []}, "empty"),
        ({"results": [{"title": "x", "url": "javascript:alert(1)", "content": "x"}]}, "error"),
        ({"results": [{"title": "x", "url": "https://example.org", "content": None}]}, "error"),
        (
            {"results": [{"title": "x", "url": "https://example.org", "content": "x" * 3000}] * 6},
            "truncated",
        ),
    ],
)
def test_web_search_empty_invalid_and_bounded_results(model_server, payload, expected):
    search = TavilySearch(
        "test-key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, search_tool=search) as runtime:
            event = tool_turn(model_server, runtime, "search", query="test")
    if expected == "error":
        assert event["status"] == "error" and event["error"] == "search_invalid_response"
    elif expected == "empty":
        assert event["result"]["matches"] == [] and "无命中" in event["result"]["notice"]
    else:
        assert len(event["result"]["matches"]) == 5 and event["result"]["truncated"] is True
        assert len(event["result"]["matches"][0]["content"]) == 2000
        assert event["result"]["matches"][0]["truncated"] is True


def test_cli_selects_network_mode_from_env_and_flag_overrides(model_server):
    for args, mode in [((), "tavily 联网搜索"), (("--search-provider", "mock"), "mock 模拟资料")]:
        result = run_cli(
            model_server,
            "/exit\n",
            overrides={"SEARCH_PROVIDER": "tavily", "TAVILY_API_KEY": "test-key"},
            args=args,
        )
        assert result.returncode == 0 and mode in result.stdout
        assert "test-key" not in result.stdout + result.stderr


def test_cli_rejects_invalid_search_provider(model_server):
    result = run_cli(model_server, "/exit\n", overrides={"SEARCH_PROVIDER": "unknown"})
    assert result.returncode == 2 and "SEARCH_PROVIDER" in result.stderr
