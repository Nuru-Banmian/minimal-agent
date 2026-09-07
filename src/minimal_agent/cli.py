import argparse
import json
import sys

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import ConfigError, Settings
from minimal_agent.runtime import Runtime
from minimal_agent.sessions import SessionError


def main() -> int:
    parser = argparse.ArgumentParser(description="支持 SQLite 会话恢复的最小 Agent")
    parser.add_argument("--user-id", default="local", help="本地用户标识（不是认证）")
    parser.add_argument("--session-id", default="default", help="该用户的会话标识")
    parser.add_argument(
        "--db", default="agent.sqlite3", help="SQLite 路径；默认当前目录 agent.sqlite3"
    )
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
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
                trace=lambda event: print("trace: " + json.dumps(event, ensure_ascii=False)),
            ) as runtime,
        ):
            print(f"当前会话：user_id={args.user_id} session_id={args.session_id} db={args.db}")
            print("最小聊天 CLI：空输入跳过，输入 /exit 或 /quit 退出。")
            while True:
                text = input("你：").strip()
                if text.lower() in {"/exit", "/quit"}:
                    break
                if not text:
                    continue
                try:
                    answer = runtime.run(text)
                except (ModelError, SessionError) as error:
                    print(f"请求失败：{error} 本轮未写入历史。", file=sys.stderr)
                    continue
                print(f"助手：{answer}")
    except SessionError as error:
        print(f"会话错误：{error}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print()
    print("再见！")
    return 0
