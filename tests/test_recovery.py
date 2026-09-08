import json
import sqlite3

import pytest
from test_cli import run_cli
from test_runtime import call, reply

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import Settings
from minimal_agent.runtime import Runtime
from minimal_agent.sessions import SessionError


@pytest.mark.parametrize(
    "failure,code",
    [
        (RuntimeError("private secret"), "tool_exception"),
        (sqlite3.OperationalError("private database"), "database_error"),
    ],
)
def test_tool_failure_keeps_success_and_can_continue(model_server, failure, code):
    def broken_search(query):
        raise failure

    reply(model_server, [call("good"), call("bad", name="search", arguments='{"query":"x"}')])
    model_server.answer("计算成功，搜索失败")
    model_server.answer("下一轮正常")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, search_tool=broken_search) as runtime:
            assert runtime.run("分别处理") == "计算成功，搜索失败"
            assert runtime.run("继续") == "下一轮正常"
    model_server.requests.get_nowait()
    messages = model_server.requests.get_nowait()["body"]["messages"]
    assert [m["tool_call_id"] for m in messages[-2:]] == ["good", "bad"]
    assert json.loads(messages[-2]["content"]) == {"status": "ok", "result": 20}
    assert json.loads(messages[-1]["content"]) == {"status": "error", "error": code}


def test_replayed_todo_is_once_per_turn_but_new_request_can_add(model_server, tmp_path):
    add = call("same", name="todo", arguments='{"action":"add","content":"报告"}')
    reply(model_server, [add])
    reply(model_server, [add])
    model_server.answer("已添加一次")
    reply(model_server, [add])
    model_server.answer("新请求已添加")
    reply(model_server, [call("list", name="todo", arguments='{"action":"list"}')])
    model_server.answer("两条")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=tmp_path / "replay.sqlite3") as runtime:
            runtime.run("添加报告")
            runtime.run("再添加报告")
            runtime.run("查看")
    requests = [model_server.requests.get_nowait()["body"] for _ in range(7)]
    first = json.loads(requests[1]["messages"][-1]["content"])
    replay = json.loads(requests[2]["messages"][-1]["content"])
    assert first == replay
    items = json.loads(requests[-1]["messages"][-1]["content"])["result"]["items"]
    assert len(items) == 2
    assert items[0]["id"] != items[1]["id"]


def test_restart_repairs_interrupted_calls_without_replaying_writes(model_server, tmp_path):
    database = tmp_path / "interrupted.sqlite3"

    def interrupt(query):
        raise KeyboardInterrupt

    reply(
        model_server,
        [
            call("saved", name="todo", arguments='{"action":"add","content":"报告"}'),
            call("interrupted", name="search", arguments='{"query":"x"}'),
            call("unstarted", name="todo", arguments='{"action":"add","content":"不能添加"}'),
        ],
    )
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database, search_tool=interrupt) as runtime:
            with pytest.raises(KeyboardInterrupt):
                runtime.run("部分执行")
        reply(model_server, [call("list", name="todo", arguments='{"action":"list"}')])
        model_server.answer("只保存报告")
        with Runtime(client, db_path=database) as runtime:
            assert runtime.run("检查待办") == "只保存报告"
    model_server.requests.get_nowait()
    history = model_server.requests.get_nowait()["body"]["messages"]
    results = [m for m in history if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in results] == ["saved", "interrupted", "unstarted"]
    assert json.loads(results[0]["content"])["result"]["outcome"] == "added"
    assert [json.loads(m["content"])["error"] for m in results[1:]] == ["interrupted"] * 2
    assert "中断" in history[-2]["content"]
    listing = model_server.requests.get_nowait()["body"]["messages"][-1]
    assert [i["content"] for i in json.loads(listing["content"])["result"]["items"]] == ["报告"]


@pytest.mark.parametrize(
    "status,code",
    [(401, "authentication"), (429, "rate_limit"), (500, "api_error"), (200, "empty_response")],
)
def test_api_failure_trace_counts_attempt_and_next_turn(model_server, status, code):
    model_server.replies.put((status, {"choices": []}))
    model_server.answer("恢复")
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, trace=events.append) as runtime:
            with pytest.raises(ModelError):
                runtime.run("失败")
            stop = events[-1]
            assert stop["error"] == code
            assert stop["actual_requests"] == 1
            assert stop["status"] == "error"
            assert stop["elapsed_ms"] >= 0
            assert stop["user_id"] == "local" and stop["session_id"] == "default"
            assert stop["turn_id"]
            assert runtime.run("继续") == "恢复"
            assert events[-1]["actual_requests"] == 1
    assert model_server.requests.qsize() == 2


def test_cli_jsonl_trace_is_bounded_redacted_and_complete(model_server, tmp_path):
    trace = tmp_path / "trace.jsonl"
    reply(
        model_server,
        [
            call(
                "large",
                name="search",
                arguments=json.dumps(
                    {
                        "query": "test-key Authorization: Bearer hidden-token " + "汉" * 2000,
                    }
                ),
            )
        ],
    )
    model_server.answer("结束")
    result = run_cli(model_server, "搜索\n/exit\n", args=["--trace-file", str(trace)])
    assert result.returncode == 0, result.stderr
    raw = trace.read_text(encoding="utf-8")
    assert "test-key" not in raw + result.stdout
    assert "hidden-token" not in raw + result.stdout
    events = [json.loads(line) for line in raw.splitlines()]
    tool = next(e for e in events if e["event"] == "tool")
    assert tool["arguments"]["truncated"] is True
    assert tool["tool_call_id"] == "large"
    assert len(json.dumps(tool, ensure_ascii=False).encode()) < 12000
    assert events[-1]["reason"] == "final_answer"
    assert events[-1]["actual_requests"] == 2
    assert not any(e["event"] == "action" for e in events)


@pytest.mark.parametrize("arguments,category", [("{", "malformed_json"), ("{}", "schema_mismatch")])
def test_argument_errors_are_distinguished_and_correctable(model_server, arguments, category):
    reply(model_server, [call(arguments=arguments)])
    reply(model_server, [call("correct")])
    model_server.answer("20")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client) as runtime:
            assert runtime.run("计算") == "20"
    model_server.requests.get_nowait()
    error = json.loads(model_server.requests.get_nowait()["body"]["messages"][-1]["content"])
    assert error["category"] == category


@pytest.mark.parametrize("fault", ["ledger", "checkpoint"])
def test_database_fault_never_duplicates_or_loses_committed_todo(
    model_server, tmp_path, monkeypatch, fault
):
    original_connect = sqlite3.connect
    armed = True
    checkpoints = 0

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            nonlocal armed, checkpoints
            if sql.startswith("INSERT INTO pending_turns"):
                checkpoints += 1
            if armed and (
                (fault == "ledger" and sql.startswith("INSERT INTO tool_results"))
                or (
                    fault == "checkpoint"
                    and sql.startswith("INSERT INTO pending_turns")
                    and checkpoints == 2
                )
            ):
                armed = False
                raise sqlite3.OperationalError("injected write failure")
            return super().execute(sql, parameters)

    monkeypatch.setattr(
        sqlite3, "connect", lambda *a, **kw: original_connect(*a, **kw, factory=FaultConnection)
    )
    database = tmp_path / "atomic.sqlite3"
    reply(model_server, [call("write", name="todo", arguments='{"action":"add","content":"报告"}')])
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database) as runtime:
            if fault == "checkpoint":
                with pytest.raises(SessionError):
                    runtime.run("添加")
            else:
                model_server.answer("数据库失败，未添加")
                assert runtime.run("添加") == "数据库失败，未添加"
        reply(model_server, [call("list", name="todo", arguments='{"action":"list"}')])
        model_server.answer("已检查")
        with Runtime(client, db_path=database) as runtime:
            runtime.run("检查")
    requests = []
    while not model_server.requests.empty():
        requests.append(model_server.requests.get_nowait()["body"]["messages"])
    items = json.loads(requests[-1][-1]["content"])["result"]["items"]
    assert len(items) == (1 if fault == "checkpoint" else 0)
    if fault == "checkpoint":
        recovered = [m for m in requests[-2] if m["role"] == "tool"][0]
        assert json.loads(recovered["content"])["result"]["item"]["id"] == items[0]["id"]


def test_summary_trace_counts_actual_requests_and_compression(model_server, tmp_path):
    from test_memory import seed_history

    from minimal_agent.memory import MemorySettings

    events = []
    database = tmp_path / "summary.sqlite3"
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        seed_history(client, model_server, database)
        model_server.answer("小林")
        model_server.answer("恢复记忆")
        with Runtime(
            client,
            db_path=database,
            trace=events.append,
            memory=MemorySettings(context_bytes=14000, keep_recent_turns=1),
        ) as runtime:
            runtime.run("继续")
    compact = next(e for e in events if e["event"] == "memory_compacted")
    assert compact["before_bytes"] > compact["after_bytes"] > 0
    assert events[-1]["actual_requests"] == model_server.requests.qsize() == 2
    assert [e["purpose"] for e in events if e["event"] == "model_response"] == [
        "summary",
        "decision",
    ]


@pytest.mark.parametrize("error,code", [("timeout", "timeout"), ("network", "network")])
def test_transport_failures_are_counted_without_retry_and_next_turn_works(
    model_server, monkeypatch, error, code
):
    import httpx

    original = httpx.HTTPTransport.handle_request
    attempts = []

    def transport(self, request):
        attempts.append(request)
        if len(attempts) == 1:
            if error == "timeout":
                raise httpx.ReadTimeout("private")
            raise httpx.ConnectError("private")
        return original(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    model_server.answer("恢复")
    events = []
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, trace=events.append) as runtime:
            with pytest.raises(ModelError):
                runtime.run("失败")
            assert len(attempts) == events[-1]["actual_requests"] == 1
            assert events[-1]["error"] == code
            assert runtime.run("继续") == "恢复"


def test_cli_step_limit_trace_and_followup(model_server, tmp_path):
    for _ in range(2):
        reply(model_server, [call(name="missing")])
    model_server.answer("下一轮恢复")
    trace = tmp_path / "limit.jsonl"
    result = run_cli(
        model_server,
        "循环\n继续\n/exit\n",
        args=[
            "--max-steps",
            "2",
            "--trace-file",
            str(trace),
        ],
    )
    assert result.returncode == 0
    assert "任务未完成" in result.stderr
    assert "助手：下一轮恢复" in result.stdout
    stops = [
        e
        for line in trace.read_text(encoding="utf-8").splitlines()
        if (e := json.loads(line))["event"] == "stop"
    ]
    assert [(e["reason"], e["actual_requests"]) for e in stops] == [
        ("step_limit", 2),
        ("final_answer", 1),
    ]


def test_todo_reads_stay_fresh_when_model_reuses_read_id(model_server):
    listing = call("read", name="todo", arguments='{"action":"list"}')
    reply(model_server, [listing])
    reply(model_server, [call("write", name="todo", arguments='{"action":"add","content":"报告"}')])
    reply(model_server, [listing])
    model_server.answer("一条")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client) as runtime:
            runtime.run("查询、添加、再查询")
    requests = [model_server.requests.get_nowait()["body"]["messages"] for _ in range(4)]
    assert json.loads(requests[1][-1]["content"])["result"]["items"] == []
    assert len(json.loads(requests[-1][-1]["content"])["result"]["items"]) == 1
