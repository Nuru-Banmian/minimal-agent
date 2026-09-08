import json

import pytest
from test_cli import run_cli
from test_runtime import call, reply

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import Settings
from minimal_agent.memory import MemorySettings
from minimal_agent.runtime import Runtime


def test_compression_restores_summary_and_recent_turn_after_restart(model_server, tmp_path):
    database = tmp_path / "memory.sqlite3"
    config = MemorySettings(context_bytes=14000, keep_recent_turns=1)
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database, memory=config) as runtime:
            model_server.answer("记住了" + "a" * 4000)
            runtime.run("我叫小林，周五交报告，不要安排周末工作。")
            model_server.answer("近期回复" + "b" * 4000)
            runtime.run("最新进度")
        model_server.requests.get_nowait()
        model_server.requests.get_nowait()
        model_server.answer("小林；周五交报告；不安排周末工作。")
        model_server.answer("小林")
        events = []
        with Runtime(client, db_path=database, memory=config, trace=events.append) as runtime:
            assert runtime.run("我叫什么？") == "小林"
        summary = model_server.requests.get_nowait()["body"]
        assert "最新进度" not in str(summary)
        assert "我叫什么？" not in str(summary)
        assert "周五交报告" in str(summary)
        request = model_server.requests.get_nowait()["body"]
        assert request["messages"][1]["role"] == "user"
        assert "小林；周五交报告" in request["messages"][1]["content"]
        assert "a" * 4000 not in str(request)
        assert "b" * 4000 in str(request)
        assert len([e for e in events if e["event"] == "model_request"]) == 2
        model_server.answer("周五")
        with Runtime(client, db_path=database, memory=config) as runtime:
            assert runtime.run("哪天交报告？") == "周五"
        restored = model_server.requests.get_nowait()["body"]
        assert "小林；周五交报告" in str(restored)
        assert model_server.requests.empty()


def test_large_tool_result_is_bounded_but_raw_history_survives(model_server, tmp_path):
    database = tmp_path / "tool.sqlite3"
    reply(model_server, [call(name="search", arguments='{"query":"large"}')])
    model_server.answer("资料已裁剪")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(
            client,
            db_path=database,
            memory=MemorySettings(tool_result_bytes=400),
            search_tool=lambda query: {"content": "汉" * 2000},
        ) as runtime:
            runtime.run("搜索")
        model_server.requests.get_nowait()
        tool = model_server.requests.get_nowait()["body"]["messages"][-1]
        assert len(tool["content"].encode()) <= 400
        assert json.loads(tool["content"])["truncated"] is True
        model_server.answer("恢复原始资料")
        with Runtime(
            client, db_path=database, memory=MemorySettings(tool_result_bytes=10000)
        ) as rt:
            rt.run("继续")
        restored = model_server.requests.get_nowait()["body"]["messages"]
        assert json.loads(restored[3]["content"])["result"]["content"] == "汉" * 2000


def test_cli_rejects_oversized_input_without_model_request(model_server):
    result = run_cli(
        model_server,
        "汉" * 4000 + "\n/exit\n",
        {
            "MEMORY_CONTEXT_BYTES": "10000",
        },
    )
    assert "过长" in result.stderr
    assert model_server.requests.empty()


def seed_history(client, server, database):
    with Runtime(client, db_path=database) as runtime:
        reply(server, [call("old-tool")])
        server.answer("旧事实：小林" + "a" * 4000)
        runtime.run("我叫小林，计算12+8")
        server.answer("近期内容" + "b" * 4000)
        runtime.run("近期问题")
    for _ in range(3):
        server.requests.get_nowait()


@pytest.mark.parametrize("failure", ["empty", "long", "http", "timeout", "tools"])
def test_failed_summary_keeps_all_history_and_only_attempts_once(model_server, tmp_path, failure):
    database = tmp_path / "failed.sqlite3"
    events = []
    config = MemorySettings(
        context_bytes=14000,
        keep_recent_turns=1,
        summary_timeout_seconds=0.05,
    )
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        seed_history(client, model_server, database)
        if failure == "http":
            model_server.replies.put((500, {}))
        elif failure == "tools":
            reply(model_server, [call("forbidden")])
        else:
            model_server.answer(" " if failure == "empty" else "x" * 5000)
        if failure == "timeout":
            model_server.delay = 0.2
        with Runtime(client, db_path=database, memory=config, trace=events.append) as runtime:
            with pytest.raises(ModelError):
                runtime.run("本轮不应被摘要")
        model_server.delay = 0
        request = model_server.requests.get_nowait()["body"]
        source = json.loads(request["messages"][1]["content"])["completed_turns"]
        assert [m["role"] for m in source] == ["user", "assistant", "tool", "assistant"]
        assert source[1]["tool_calls"][0]["id"] == source[2]["tool_call_id"]
        assert "近期问题" not in str(source) and "本轮不应被摘要" not in str(source)
        assert "tools" not in request
        assert len([e for e in events if e["event"] == "model_request"]) == 1
        model_server.answer("重新恢复")
        with Runtime(client, db_path=database) as runtime:
            runtime.run("恢复完整历史")
        restored = model_server.requests.get_nowait()["body"]["messages"]
        assert "a" * 4000 in str(restored) and "b" * 4000 in str(restored)
        assert "本轮不应被摘要" not in str(restored)


def test_summary_isolated_by_user_and_session(model_server, tmp_path):
    database = tmp_path / "isolated.sqlite3"
    config = MemorySettings(context_bytes=14000, keep_recent_turns=1)
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        seed_history(client, model_server, database)
        model_server.answer("小林的私密历史")
        model_server.answer("完成")
        with Runtime(client, db_path=database, memory=config) as rt:
            rt.run("压缩")
        model_server.requests.get_nowait()
        request = model_server.requests.get_nowait()["body"]
        assert "a" * 4000 not in str(request)
        for identity in [{"user_id": "other"}, {"session_id": "other"}]:
            model_server.answer("新会话")
            with Runtime(client, db_path=database, memory=config, **identity) as rt:
                rt.run("你好")
            messages = model_server.requests.get_nowait()["body"]["messages"]
            assert messages[1:] == [{"role": "user", "content": "你好"}]


@pytest.mark.parametrize("mode", ["recent", "summary_input", "summary_does_not_fit"])
def test_irreducible_context_reports_error_without_committing_summary(model_server, tmp_path, mode):
    database = tmp_path / "overflow.sqlite3"
    config = MemorySettings(
        context_bytes=14000,
        keep_recent_turns=2 if mode == "recent" else 1,
        summary_input_bytes=100 if mode == "summary_input" else 256000,
    )
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        seed_history(client, model_server, database)
        if mode == "summary_does_not_fit":
            model_server.answer("s" * 4000)
        with Runtime(client, db_path=database, memory=config) as rt:
            with pytest.raises(ModelError, match="过长|预算"):
                rt.run("继续")
        if mode == "summary_does_not_fit":
            model_server.requests.get_nowait()
        assert model_server.requests.empty()
        model_server.answer("恢复")
        with Runtime(client, db_path=database) as rt:
            rt.run("恢复")
        assert "a" * 4000 in str(model_server.requests.get_nowait()["body"])


def test_current_tool_turn_is_not_compressed_on_overflow(model_server):
    reply(model_server, [call("a"), call("b")], content="x" * 10000)
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, memory=MemorySettings(context_bytes=14000), trace=events.append) as rt:
            with pytest.raises(ModelError, match="过长"):
                rt.run("计算两次")
    assert len([e for e in events if e["event"] == "model_request"]) == 1
    assert len([e for e in events if e["event"] == "tool"]) == 2
    model_server.requests.get_nowait()
    assert model_server.requests.empty()


def test_tool_growth_can_compress_old_turns_once_without_splitting_current(model_server, tmp_path):
    database = tmp_path / "growing.sqlite3"
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        seed_history(client, model_server, database)
        reply(model_server, [call("current")], content="z" * 3000)
        model_server.answer("小林，计算结果20")
        model_server.answer("20")
        with Runtime(
            client,
            db_path=database,
            memory=MemorySettings(context_bytes=18000, keep_recent_turns=1),
        ) as rt:
            assert rt.run("继续计算") == "20"
        model_server.requests.get_nowait()
        summary = model_server.requests.get_nowait()["body"]
        assert "z" * 3000 not in str(summary)
        final = model_server.requests.get_nowait()["body"]["messages"]
        assert final[-2]["tool_calls"][0]["id"] == final[-1]["tool_call_id"] == "current"
        assert "z" * 3000 in str(final)


def test_already_compacted_turn_does_not_make_second_summary_request(model_server, tmp_path):
    database = tmp_path / "once.sqlite3"
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        seed_history(client, model_server, database)
        model_server.answer("小林")
        reply(model_server, [call("large")], content="z" * 9000)
        with Runtime(
            client,
            db_path=database,
            trace=events.append,
            memory=MemorySettings(context_bytes=14000, keep_recent_turns=1),
        ) as rt:
            with pytest.raises(ModelError, match="过长"):
                rt.run("计算")
        assert len([e for e in events if e["event"] == "model_request"]) == 2
        model_server.requests.get_nowait()
        model_server.requests.get_nowait()
        assert model_server.requests.empty()


@pytest.mark.parametrize(
    "name,value",
    [
        ("CONTEXT_BYTES", "abc"),
        ("CONTEXT_BYTES", "4096"),
        ("OUTPUT_TOKENS", "0"),
        ("KEEP_RECENT_TURNS", "0"),
        ("SUMMARY_BYTES", "-1"),
        ("SUMMARY_INPUT_BYTES", "0"),
        ("SUMMARY_TIMEOUT_SECONDS", "nan"),
        ("SUMMARY_TIMEOUT_SECONDS", "-2"),
        ("TOOL_RESULT_BYTES", "10"),
    ],
)
def test_cli_rejects_invalid_memory_settings(model_server, name, value):
    result = run_cli(model_server, "/exit\n", {"MEMORY_" + name: value})
    assert result.returncode == 2
    assert "配置错误" in result.stderr
    assert model_server.requests.empty()


def test_tool_schema_is_included_in_budget(model_server):
    from minimal_agent.tools import ToolRegistry

    registry = ToolRegistry()
    registry.register("large", "x" * 15000, {"type": "object"}, lambda: "ok")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, registry=registry, memory=MemorySettings(context_bytes=14000)) as rt:
            with pytest.raises(ModelError, match="Schema"):
                rt.run("你好")
    assert model_server.requests.empty()
