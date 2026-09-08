import json

import pytest
from test_runtime import call, reply

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import Settings
from minimal_agent.runtime import Runtime
from minimal_agent.sessions import SessionError


def test_runtime_restores_ordered_history_and_isolates_sessions(model_server, tmp_path):
    database = tmp_path / "history.sqlite3"
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        for user, session, fact in [("u", "1", "小林"), ("u", "2", "小王"), ("v", "1", "小李")]:
            model_server.answer(f"你好，{fact}")
            with Runtime(client, db_path=database, user_id=user, session_id=session) as runtime:
                runtime.run(f"我叫{fact}")
            assert model_server.requests.get_nowait()["body"]["messages"][1:] == [
                {"role": "user", "content": f"我叫{fact}"}
            ]
        for user, session, fact in [("u", "1", "小林"), ("u", "2", "小王"), ("v", "1", "小李")]:
            model_server.answer(fact)
            with Runtime(client, db_path=database, user_id=user, session_id=session) as runtime:
                assert runtime.run("我叫什么") == fact
            assert model_server.requests.get_nowait()["body"]["messages"][1:] == [
                {"role": "user", "content": f"我叫{fact}"},
                {"role": "assistant", "content": f"你好，{fact}"},
                {"role": "user", "content": "我叫什么"},
            ]


def test_runtime_rejects_same_session_until_owner_closes(model_server, tmp_path):
    database = tmp_path / "history.sqlite3"
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database) as first:
            with pytest.raises(SessionError, match="占用"):
                Runtime(client, db_path=database)
            with Runtime(client, db_path=database, session_id="other") as second:
                model_server.answer("甲")
                first.run("第一条")
                model_server.answer("乙")
                second.run("另一会话")
                model_server.answer("丙")
                first.run("第二条")
        with Runtime(client, db_path=database) as resumed:
            model_server.answer("已恢复")
            resumed.run("追问")
        requests = [model_server.requests.get_nowait()["body"]["messages"] for _ in range(4)]
        assert requests[-1][1:] == [
            {"role": "user", "content": "第一条"},
            {"role": "assistant", "content": "甲"},
            {"role": "user", "content": "第二条"},
            {"role": "assistant", "content": "丙"},
            {"role": "user", "content": "追问"},
        ]


def test_restart_preserves_complete_tool_pairs_and_rejects_model_identity(model_server, tmp_path):
    database = tmp_path / "history.sqlite3"
    forged = call(
        "forged",
        arguments=json.dumps(
            {"operation": "add", "a": 12, "b": 8, "user_id": "victim", "session_id": "secret"}
        ),
    )
    correct = call("correct")
    reply(model_server, [forged, correct], content="计算")
    model_server.answer("20")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database) as runtime:
            runtime.run("12+8")
        model_server.requests.get_nowait()
        completed = model_server.requests.get_nowait()["body"]["messages"]
        assert completed[-3]["tool_calls"] == [forged, correct]
        assert [message["tool_call_id"] for message in completed[-2:]] == ["forged", "correct"]
        assert json.loads(completed[-2]["content"])["status"] == "error"
        assert json.loads(completed[-1]["content"]) == {"status": "ok", "result": 20}
        reply(model_server, [call("followup", "divide", 20, 4)])
        model_server.answer("5")
        with Runtime(client, db_path=database) as runtime:
            assert runtime.run("结果除以4") == "5"
        assert model_server.requests.get_nowait()["body"]["messages"] == [
            *completed,
            {"role": "assistant", "content": "20"},
            {"role": "user", "content": "结果除以4"},
        ]
        model_server.requests.get_nowait()
        model_server.answer("新会话")
        with Runtime(client, db_path=database, user_id="victim", session_id="secret") as runtime:
            runtime.run("你好")
        assert model_server.requests.get_nowait()["body"]["messages"][1:] == [
            {"role": "user", "content": "你好"}
        ]


def test_failed_tool_turn_does_not_damage_durable_history(model_server, tmp_path):
    database = tmp_path / "history.sqlite3"
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with Runtime(client, db_path=database) as runtime:
            model_server.answer("记住了")
            runtime.run("我叫小林")
            reply(model_server, [call()])
            model_server.replies.put((500, {}))
            with pytest.raises(ModelError):
                runtime.run("失败计算")
        for _ in range(3):
            model_server.requests.get_nowait()
        model_server.answer("小林")
        with Runtime(client, db_path=database) as runtime:
            runtime.run("我叫什么")
        history = model_server.requests.get_nowait()["body"]["messages"][1:]
        assert history[:2] == [
            {"role": "user", "content": "我叫小林"},
            {"role": "assistant", "content": "记住了"},
        ]
        assert history[-1] == {"role": "user", "content": "我叫什么"}
        assert history[3]["tool_calls"][0]["id"] == history[4]["tool_call_id"]
        assert json.loads(history[4]["content"]) == {"status": "ok", "result": 20}
        assert "中断" in history[-2]["content"]
