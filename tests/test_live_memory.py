"""Explicit real-model memory demonstration; no scripted model or substituted tools."""

import json
import os
from datetime import UTC, datetime

import pytest

from minimal_agent.client import ModelClient
from minimal_agent.config import Settings
from minimal_agent.memory import MemorySettings
from minimal_agent.runtime import Runtime

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_API") != "1", reason="真实 API 验证未显式开启"
)


def test_real_memory_recalls_facts_and_completes_todo_after_restart(tmp_path):
    settings = Settings.from_env()
    config = MemorySettings(context_bytes=18000, keep_recent_turns=1, summary_bytes=2048)
    database = tmp_path / "live-memory.sqlite3"
    events = []
    print(f"UTC={datetime.now(UTC).isoformat()} model={settings.model}; real API, real SQLite/todo")
    with ModelClient(settings) as client:

        def turn(prompt):
            start = len(events)
            with Runtime(
                client,
                db_path=database,
                memory=config,
                trace=events.append,
                user_id="live",
                session_id="memory",
            ) as runtime:
                answer = runtime.run(prompt)
            print(
                json.dumps(
                    {"prompt": prompt, "answer": answer, "events": events[start:]},
                    ensure_ascii=False,
                )
            )
            return answer, events[start:]

        _, first = turn(
            "我叫小林，项目代号是青竹，报告周五交，不安排周末工作。"
            "请记住这些事实，并用 todo 添加一个提交青竹报告的待办。"
        )
        item = next(
            e["result"]["item"]
            for e in first
            if e["event"] == "tool"
            and e["name"] == "todo"
            and e.get("result", {}).get("outcome") == "added"
        )
        for index in range(5):
            turn(f"背景材料第{index + 1}段：以下是无意义的填充，请仅回复收到。\n" + "abcdef " * 430)
        assert any(e["event"] == "memory_compacted" for e in events)
        answer, _ = turn("我叫什么？项目代号、交付日期、工作日约束分别是什么？")
        assert all(word in answer for word in ["小林", "青竹", "周五", "周末"])
        _, completion = turn("请先查询我的待办，再完成提交报告那一项，并说明执行结果。")
        assert any(
            e["event"] == "tool"
            and e["name"] == "todo"
            and e.get("result", {}).get("outcome") == "listed"
            for e in completion
        )
        assert any(
            e["event"] == "tool"
            and e["name"] == "todo"
            and e.get("result", {}).get("outcome") == "completed"
            and e["result"]["item"]["id"] == item["id"]
            for e in completion
        )
