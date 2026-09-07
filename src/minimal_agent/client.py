from types import TracebackType
from typing import Literal, TypedDict

import httpx

from minimal_agent.config import Settings


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ModelError(Exception):
    """A safe, user-facing model service error."""


class ModelClient:
    """Own the synchronous OpenAI-compatible HTTP request and response conversion."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            trust_env=False,
        )

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.http.close()

    def complete(self, messages: list[Message]) -> str:
        try:
            response = self.http.post(
                f"{self.settings.base_url.rstrip('/')}/chat/completions",
                json={
                    "model": self.settings.model,
                    "messages": messages,
                    "stream": False,
                    "enable_thinking": False,
                },
            )
        except httpx.TimeoutException:
            raise ModelError("模型请求超时，请稍后重试或调整 LLM_TIMEOUT_SECONDS。") from None
        except httpx.RequestError:
            raise ModelError("无法连接模型服务：请检查网络与 LLM_BASE_URL。") from None
        if response.is_error:
            hints = {
                401: "鉴权失败：请检查 DASHSCOPE_API_KEY 与地域是否匹配。",
                403: "权限不足：请检查账号的模型访问权限与地域。",
                429: "请求过多或额度不足：请稍后重试并检查额度。",
            }
            hint = hints.get(response.status_code)
            if hint is None:
                hint = (
                    "模型服务暂时不可用，请稍后重试。"
                    if response.status_code >= 500
                    else "请求被拒绝：请检查模型名称、base URL 与账号配置。"
                )
            raise ModelError(hint)
        try:
            choice = response.json()["choices"][0]
            message = choice["message"]
            content = message["content"]
            valid = (
                choice.get("finish_reason") == "stop"
                and message.get("role") == "assistant"
                and not message.get("tool_calls")
                and isinstance(content, str)
                and bool(content.strip())
            )
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            valid = False
            content = None
        if not valid or not isinstance(content, str):
            raise ModelError("模型未返回有效的完整文本回答；本步仅支持普通聊天，请重试。")
        return content
