import json

import pytest
from test_runtime import call, reply

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import Settings
from minimal_agent.runtime import Runtime


def tool_call(name, **arguments):
    return call(name=name, arguments=json.dumps(arguments, ensure_ascii=False))


def tool_turn(server, runtime, name, **arguments):
    events = []
    runtime.trace = events.append
    reply(server, [tool_call(name, **arguments)])
    server.answer("已读取工具结果")
    runtime.run("执行本次工具请求")
    return next(event for event in events if event["event"] == "tool")


def test_search_returns_fixed_mock_weather_through_runtime(model_server):
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client) as runtime:
            event = tool_turn(model_server, runtime, "search", query="上海天气")
    assert event["status"] == "ok"
    assert event["result"] == {
        "mock": True,
        "notice": "模拟资料，非实时信息。",
        "matches": [
            {
                "title": "上海示例天气（2026-09-01）",
                "source": "mock:weather:shanghai:2026-09-01",
                "content": "2026-09-01 上海：小雨，22–27°C，出门建议带伞。"
                "仅为模拟示例，非实时天气。",
                "mock": True,
            }
        ],
    }
    request = model_server.requests.get_nowait()["body"]
    assert {tool["function"]["name"] for tool in request["tools"]} >= {"calculator", "search"}


def test_search_to_todo_chain_survives_restart(model_server, tmp_path):
    database = tmp_path / "agent.sqlite3"
    reply(model_server, [tool_call("search", query="上海天气")])
    reply(model_server, [tool_call("todo", action="add", content="带伞")])
    model_server.answer("模拟、非实时天气提示小雨，已添加带伞待办。")
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database, trace=events.append) as runtime:
            runtime.run("查上海的示例天气，帮我记一个带伞的待办")
        search_event, added = [event for event in events if event["event"] == "tool"]
        assert search_event["result"]["matches"][0]["mock"] is True
        assert added["status"] == "ok"
        item = added["result"]["item"]
        assert item["content"] == "带伞" and item["completed"] is False
        assert isinstance(item["id"], str) and item["id"]
        requests = [model_server.requests.get_nowait()["body"] for _ in range(3)]
        assert (
            json.loads(requests[1]["messages"][-1]["content"])["result"] == search_event["result"]
        )
        assert json.loads(requests[2]["messages"][-1]["content"])["result"]["item"] == item
        with Runtime(client, db_path=database) as runtime:
            listed = tool_turn(model_server, runtime, "todo", action="list")
        assert listed["result"]["items"] == [item]


def test_todo_completion_is_isolated_idempotent_and_durable(model_server, tmp_path):
    database = tmp_path / "agent.sqlite3"
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database, user_id="u", session_id="1") as first:
            item = tool_turn(model_server, first, "todo", action="add", content="带伞")["result"][
                "item"
            ]
            for user, session in [("u", "2"), ("v", "1")]:
                with Runtime(client, db_path=database, user_id=user, session_id=session) as other:
                    assert (
                        tool_turn(model_server, other, "todo", action="list")["result"]["items"]
                        == []
                    )
                    rejected = tool_turn(
                        model_server, other, "todo", action="complete", id=item["id"]
                    )
                    assert rejected["result"]["outcome"] == "not_found"
                    tool_turn(model_server, other, "todo", action="add", content="提交周报")
            completed = tool_turn(model_server, first, "todo", action="complete", id=item["id"])
            assert completed["result"] == {
                "outcome": "completed",
                "item": {**item, "completed": True},
            }
            repeated = tool_turn(model_server, first, "todo", action="complete", id=item["id"])
            assert repeated["result"]["outcome"] == "already_completed"
        with Runtime(client, db_path=database, user_id="u", session_id="1") as first:
            assert tool_turn(model_server, first, "todo", action="list")["result"]["items"] == [
                {**item, "completed": True}
            ]
        for user, session in [("u", "2"), ("v", "1")]:
            with Runtime(client, db_path=database, user_id=user, session_id=session) as other:
                items = tool_turn(model_server, other, "todo", action="list")["result"]["items"]
                assert len(items) == 1
                assert items[0]["content"] == "提交周报" and items[0]["completed"] is False


def test_runtime_instructs_mock_disclosure_and_clarification(model_server):
    model_server.answer("请问要完成哪一项待办？")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client) as runtime:
            runtime.run("完成待办")
    request = model_server.requests.get_nowait()["body"]
    instructions = request["messages"][0]["content"]
    assert "非实时" in instructions and "固定日期" in instructions
    assert "歧义" in instructions and "澄清" in instructions
    todo = next(tool["function"] for tool in request["tools"] if tool["function"]["name"] == "todo")
    assert set(todo["parameters"]["properties"]) == {"action", "content", "id"}


@pytest.mark.parametrize("query", ["北京天气", "不存在的火星基地", "   "])
def test_search_no_match_is_explicit(model_server, query):
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client) as runtime:
            result = tool_turn(model_server, runtime, "search", query=query)["result"]
    assert result["mock"] is True and result["matches"] == []
    assert "无命中" in result["notice"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "complete"},
        {"action": "complete", "content": "带伞"},
        {"action": "complete", "id": ""},
        {"action": "add", "content": "   "},
        {"action": "add", "content": "伪造", "user_id": "victim"},
        {"action": "add", "content": "伪造", "session_id": "2"},
        {"action": "list", "content": "意外参数"},
    ],
)
def test_invalid_todo_arguments_do_not_change_state(model_server, arguments):
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client) as runtime:
            event = tool_turn(model_server, runtime, "todo", **arguments)
            assert event["status"] == "error" and event["error"] == "invalid_arguments"
            assert tool_turn(model_server, runtime, "todo", action="list")["result"]["items"] == []


def test_committed_todo_can_be_queried_after_model_failure(model_server, tmp_path):
    database = tmp_path / "agent.sqlite3"
    reply(model_server, [tool_call("todo", action="add", content="带伞")])
    model_server.replies.put((500, {}))
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database) as runtime:
            with pytest.raises(ModelError):
                runtime.run("记一个带伞待办")
        with Runtime(client, db_path=database) as runtime:
            items = tool_turn(model_server, runtime, "todo", action="list")["result"]["items"]
            assert len(items) == 1 and items[0]["content"] == "带伞"
