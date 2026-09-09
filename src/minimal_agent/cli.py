import argparse
import json
import os
import sys

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import ConfigError, Settings
from minimal_agent.memory import MemorySettings
from minimal_agent.runtime import Runtime
from minimal_agent.search import TavilySearch, search
from minimal_agent.sessions import SessionError
from minimal_agent.trace import JsonlTrace, TraceError


def main() -> int:
    parser = argparse.ArgumentParser(description="支持 SQLite 会话恢复的最小 Agent")
    parser.add_argument("--user-id", default="local", help="本地用户标识（不是认证）")
    parser.add_argument("--session-id", default="default", help="该用户的会话标识")
    parser.add_argument(
        "--search-provider",
        choices=["mock", "tavily"],
        help="搜索模式；覆盖 SEARCH_PROVIDER，默认 mock",
    )
    parser.add_argument(
        "--db", default="agent.sqlite3", help="SQLite 路径；默认当前目录 agent.sqlite3"
    )
    parser.add_argument("--trace-file", default="logs/trace.jsonl", help="本地 JSONL 执行日志")
    parser.add_argument("--max-steps", type=int, default=8, help="每轮决策请求上限；摘要最多另一次")
    args = parser.parse_args()
    if args.max_steps < 1:
        parser.error("--max-steps 必须是正整数")
    jsonl = JsonlTrace(args.trace_file)

    def trace(event: dict[str, object]) -> None:
        jsonl(event)
        print("trace: " + json.dumps(event, ensure_ascii=False))

    try:
        settings = Settings.from_env()
        memory = MemorySettings.from_env()
        provider = args.search_provider or os.environ.get("SEARCH_PROVIDER", "mock").strip()
        if provider not in {"mock", "tavily"}:
            raise ConfigError("SEARCH_PROVIDER 只能是 mock 或 tavily。")
        search_tool = (
            TavilySearch(os.environ.get("TAVILY_API_KEY", "").strip())
            if provider == "tavily"
            else search
        )
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2
    try:
        with (
            ModelClient(settings) as client,
            Runtime(
                client,
                db_path=args.db,
                user_id=args.user_id,
                session_id=args.session_id,
                search_tool=search_tool,
                memory=memory,
                max_steps=args.max_steps,
                trace=trace,
                trace_secrets=(os.environ.get("TAVILY_API_KEY", ""),),
            ) as runtime,
        ):
            print(f"当前会话：user_id={args.user_id} session_id={args.session_id} db={args.db}")
            print("搜索模式：" + ("tavily 联网搜索" if provider == "tavily" else "mock 模拟资料"))
            print("最小聊天 CLI：空输入跳过，输入 /exit 或 /quit 退出。")
            while True:
                text = input("你：").strip()
                if text.lower() in {"/exit", "/quit"}:
                    break
                if not text:
                    continue
                try:
                    answer = runtime.run(text)
                except (ModelError, SessionError, TraceError) as error:
                    print(
                        f"请求失败：{error} 本轮任务未完成；"
                        "已执行的待办可能已保存，中断调用将在下次输入时恢复状态，请先查询再重试。",
                        file=sys.stderr,
                    )
                    continue
                print(f"助手：{answer}")
    except SessionError as error:
        print(f"会话错误：{error}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print()
    print("再见！")
    return 0
