"""Opt-in simultaneous CLI sessions against the configured real model."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from queue import Queue
from threading import Thread
from time import monotonic

import pytest

from minimal_agent.config import Settings


@contextmanager
def live_window(database, trace_file, session):
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-X",
            "utf8",
            "-m",
            "minimal_agent",
            "--db",
            str(database),
            "--user-id",
            "acceptance",
            "--session-id",
            session,
            "--search-provider",
            "mock",
            "--trace-file",
            str(trace_file),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    lines = Queue()

    def read_output():
        buffer = ""
        while character := process.stdout.read(1):
            buffer += character
            if character == "\n" or buffer == "你：":
                lines.put(buffer)
                buffer = ""
        if buffer:
            lines.put(buffer)
        lines.put(None)

    reader = Thread(target=read_output, daemon=True)
    reader.start()

    def until(fragment):
        collected = []
        deadline = monotonic() + 150
        while True:
            line = lines.get(timeout=max(0.01, deadline - monotonic()))
            assert line is not None, "CLI exited before expected output (raw output omitted)"
            assert monotonic() < deadline, "CLI response deadline exceeded"
            collected.append(line)
            assert not any(word in line for word in ["请求失败：", "配置错误：", "会话错误："])
            if fragment in line:
                return collected

    def turn(prompt):
        assert process.poll() is None
        process.stdin.write(prompt + "\n")
        process.stdin.flush()
        output = until("你：")
        events = [json.loads(line.split("trace: ", 1)[1]) for line in output if "trace: " in line]
        answer = "".join(output[:-1]).split("助手：", 1)[1].strip()
        assert answer
        assert any(e["event"] == "stop" and e["reason"] == "final_answer" for e in events)
        print(
            json.dumps(
                {"session": session, "prompt": prompt, "answer": answer, "events": events},
                ensure_ascii=False,
            )
        )
        return answer, [e for e in events if e["event"] == "tool"]

    try:
        until("你：")
        yield process, turn
        process.stdin.write("/exit\n")
        process.stdin.flush()
        until("再见")
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        reader.join(timeout=10)
        process.stdin.close()
        process.stdout.close()


@pytest.mark.skipif(os.environ.get("RUN_LIVE_API") != "1", reason="真实 API 验证未显式开启")
def test_real_simultaneous_windows_isolate_and_restart(tmp_path):
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://")
    print(
        f"UTC={datetime.now(UTC).isoformat()} model={settings.model}; "
        "real API; non-streaming; enable_thinking=false; search=mock; simultaneous CLI"
    )
    database = tmp_path / "windows.sqlite3"
    created = {}
    with live_window(database, tmp_path / "one.jsonl", "one") as (first, turn1):
        with live_window(database, tmp_path / "two.jsonl", "two") as (second, turn2):
            for turn, name, task in [(turn1, "小林", "提交青竹报告"), (turn2, "小王", "购买铅笔")]:
                _, tools = turn(f"我叫{name}，请记住。用 todo 添加待办：{task}。")
                assert any(
                    e["name"] == "todo"
                    and e["status"] == "ok"
                    and e["result"].get("outcome") == "added"
                    for e in tools
                )
                created[name] = next(
                    e["result"]["item"]
                    for e in tools
                    if e["name"] == "todo" and e["result"].get("outcome") == "added"
                )
            for turn, name, other, task in [
                (turn1, "小林", "小王", "青竹"),
                (turn2, "小王", "小林", "铅笔"),
            ]:
                assert first.poll() is None and second.poll() is None
                answer, tools = turn("我叫什么？请调用 todo 列出我的全部待办。")
                assert name in answer and other not in answer
                listing = next(
                    e["result"]["items"]
                    for e in tools
                    if e["name"] == "todo"
                    and e["status"] == "ok"
                    and e["result"].get("outcome") == "listed"
                )
                assert len(listing) == 1 and task in listing[0]["content"]
                assert listing == [created[name]]
    with live_window(database, tmp_path / "restart.jsonl", "one") as (_, turn):
        answer, tools = turn("我叫什么？")
        assert "小林" in answer and "小王" not in answer
        assert not tools
        _, tools = turn("先查询待办，再完成提交报告那一项。")
        assert any(
            e["name"] == "todo"
            and e["status"] == "ok"
            and e["result"].get("outcome") == "listed"
            and e["result"]["items"] == [created["小林"]]
            for e in tools
        )
        assert any(
            e["name"] == "todo"
            and e["status"] == "ok"
            and e["result"].get("outcome") == "completed"
            and e["result"]["item"]["id"] == created["小林"]["id"]
            for e in tools
        )
