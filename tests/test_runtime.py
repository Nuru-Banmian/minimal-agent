import json

import pytest

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import Settings
from minimal_agent.runtime import Runtime


def call(id="c1", operation="add", a=12, b=8, name="calculator", arguments=None):
    return {
        "id": id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments
            if arguments is not None
            else json.dumps({"operation": operation, "a": a, "b": b}),
        },
    }


def reply(server, calls, content=None, finish="tool_calls"):
    server.replies.put(
        (
            200,
            {
                "choices": [
                    {
                        "finish_reason": finish,
                        "message": {
                            "role": "assistant",
                            "content": content,
                            "tool_calls": calls,
                        },
                    }
                ]
            },
        )
    )


def test_runtime_executes_real_calculator_before_final_answer(model_server):
    reply(model_server, [call()], content="先计算加法", finish="stop")
    model_server.answer("20")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        assert Runtime(client).run("用计算器相加") == "20"
    model_server.requests.get_nowait()
    messages = model_server.requests.get_nowait()["body"]["messages"]
    assert messages[-2]["content"] == "先计算加法"
    assert messages[-1]["tool_call_id"] == "c1"
    assert json.loads(messages[-1]["content"]) == {"status": "ok", "result": 20}


def test_runtime_direct_reply_and_followup(model_server):
    model_server.answer("你好，小林")
    model_server.answer("小林")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        runtime = Runtime(client)
        assert runtime.run("我叫小林") == "你好，小林"
        assert runtime.run("我叫什么") == "小林"
    first = model_server.requests.get_nowait()["body"]
    second = model_server.requests.get_nowait()["body"]
    assert first["tools"][0]["function"]["name"] == "calculator"
    assert second["messages"][-2:] == [
        {"role": "assistant", "content": "你好，小林"},
        {"role": "user", "content": "我叫什么"},
    ]


def test_runtime_continuous_calls_and_followup(model_server):
    reply(model_server, [call()])
    reply(model_server, [call("c2", "multiply", 20, 3)])
    model_server.answer("60")
    reply(model_server, [call("c3", "divide", 60, 4)])
    model_server.answer("15")
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        runtime = Runtime(client, trace=events.append)
        assert runtime.run("用计算器计算 (12+8)*3") == "60"
        assert runtime.run("结果再除以 4") == "15"
    requests = [model_server.requests.get_nowait()["body"] for _ in range(5)]
    assert [
        json.loads(r["messages"][-1]["content"])["result"]
        for r in (requests[1], requests[2], requests[4])
    ] == [20, 60, 15]
    assert requests[3]["messages"][:-1] == [
        *requests[2]["messages"],
        {"role": "assistant", "content": "60"},
    ]
    assert [(e["turn"], e["step"], e["result"]) for e in events if e["event"] == "tool"] == [
        (1, 1, 20),
        (1, 2, 60),
        (2, 1, 15),
    ]


def test_runtime_multiple_calls_pair_errors_and_success_in_order(model_server):
    reply(model_server, [call("bad", name="missing"), call("good", "subtract", 12, 8)])
    model_server.answer("4")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        assert Runtime(client).run("处理两个调用") == "4"
    model_server.requests.get_nowait()
    messages = model_server.requests.get_nowait()["body"]["messages"]
    assert [m["tool_call_id"] for m in messages[-2:]] == ["bad", "good"]
    assert [json.loads(m["content"]) for m in messages[-2:]] == [
        {"status": "error", "error": "unknown_tool"},
        {"status": "ok", "result": 4},
    ]


@pytest.mark.parametrize(
    "arguments",
    [
        "not-json",
        "[]",
        "null",
        "{}",
        '{"operation":"add","a":true,"b":2}',
        '{"operation":"add","a":"1","b":2}',
        '{"operation":"pow","a":1,"b":2}',
        '{"operation":"add","a":1,"b":2,"extra":3}',
        '{"operation":"add","a":NaN,"b":2}',
        '{"operation":"add","a":Infinity,"b":2}',
        '{"operation":"add","a":1e999,"b":2}',
        '{"operation":"divide","a":1,"b":0}',
        '{"operation":"multiply","a":1e308,"b":1e308}',
    ],
)
def test_runtime_bad_arguments_can_be_corrected(model_server, arguments):
    reply(model_server, [call(arguments=arguments)])
    reply(model_server, [call("fixed")])
    model_server.answer("20")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        assert Runtime(client).run("计算") == "20"
    model_server.requests.get_nowait()
    bad = model_server.requests.get_nowait()["body"]["messages"][-1]
    good = model_server.requests.get_nowait()["body"]["messages"][-1]
    assert bad["tool_call_id"] == "c1"
    assert json.loads(bad["content"])["status"] == "error"
    assert json.loads(good["content"]) == {"status": "ok", "result": 20}


def test_runtime_default_limit_counts_corrections_and_allows_next_turn(model_server):
    for step in range(8):
        reply(model_server, [call(str(step), arguments="bad-json")])
    model_server.answer("重新开始")
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        runtime = Runtime(client, trace=events.append)
        with pytest.raises(ModelError, match="8.*任务未完成"):
            runtime.run("循环")
        assert model_server.requests.qsize() == 8
        assert events[-1] == {"turn": 1, "step": 8, "event": "stop", "reason": "step_limit"}
        assert len([e for e in events if e["event"] == "tool"]) == 8
        assert runtime.run("新问题") == "重新开始"
    requests = [model_server.requests.get_nowait() for _ in range(9)]
    assert requests[-1]["body"]["messages"][1:] == [{"role": "user", "content": "新问题"}]


@pytest.mark.parametrize(
    "calls,content",
    [
        ([], None),
        ([], " "),
        ([call(), call()], "说明"),
        ([dict(call(), id="")], None),
        ([dict(call(), type="other")], None),
        (
            [{"id": "x", "type": "function", "function": {"name": "calculator", "arguments": {}}}],
            None,
        ),
        ({}, "答案"),
    ],
)
def test_runtime_protocol_errors_stop_without_executing(model_server, calls, content):
    reply(model_server, calls, content)
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with pytest.raises(ModelError, match="协议错误"):
            Runtime(client, trace=events.append).run("问题")
    assert not any(e["event"] == "tool" for e in events)
    assert events[-1]["reason"] == "model_error"
