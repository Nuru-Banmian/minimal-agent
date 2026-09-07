import sys

from minimal_agent.client import Message, ModelClient, ModelError
from minimal_agent.config import ConfigError, Settings


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2
    history: list[Message] = [{"role": "system", "content": "你是一个友好的中文助手。"}]
    print("最小聊天 CLI：空输入跳过，输入 /exit 或 /quit 退出。历史仅在本进程内保留。")
    try:
        with ModelClient(settings) as client:
            while True:
                text = input("你：").strip()
                if text.lower() in {"/exit", "/quit"}:
                    break
                if not text:
                    continue
                user_message: Message = {"role": "user", "content": text}
                try:
                    answer = client.complete([*history, user_message])
                except ModelError as error:
                    print(f"请求失败：{error} 本轮未写入历史。", file=sys.stderr)
                    continue
                history.extend([user_message, {"role": "assistant", "content": answer}])
                print(f"助手：{answer}")
    except (EOFError, KeyboardInterrupt):
        print()
    print("再见！")
    return 0
