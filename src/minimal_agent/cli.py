import json
import sys

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import ConfigError, Settings
from minimal_agent.runtime import Runtime


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2
    print("最小聊天 CLI：空输入跳过，输入 /exit 或 /quit 退出。历史仅在本进程内保留。")
    try:
        with ModelClient(settings) as client:
            runtime = Runtime(
                client, trace=lambda event: print("trace: " + json.dumps(event, ensure_ascii=False))
            )
            while True:
                text = input("你：").strip()
                if text.lower() in {"/exit", "/quit"}:
                    break
                if not text:
                    continue
                try:
                    answer = runtime.run(text)
                except ModelError as error:
                    print(f"请求失败：{error} 本轮未写入历史。", file=sys.stderr)
                    continue
                print(f"助手：{answer}")
    except (EOFError, KeyboardInterrupt):
        print()
    print("再见！")
    return 0
