from types import TracebackType
from typing import Any, Literal, NotRequired, TypedDict

import httpx

from minimal_agent.config import Settings


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None
    tool_calls: NotRequired[list[dict[str, Any]]]
    tool_call_id: NotRequired[str]


class ModelError(Exception):
    """A safe, user-facing model service error."""

    def __init__(self, message: str, code: str = "context_error") -> None:
        super().__init__(message)
        self.code = code


class ModelClient:
    """Own the synchronous OpenAI-compatible HTTP request and response conversion."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.request_count = 0
        self.http = httpx.Client(
            timeout=settings.timeout_seconds,
            headers={"Authorization": f"Bearer {settings.api_key}"},
            trust_env=False,
            transport=httpx.HTTPTransport(retries=0, trust_env=False),
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
        message = self.decide(messages)
        if message.get("tool_calls") or not isinstance(message["content"], str):
            raise ModelError("模型未返回有效的完整文本回答。")
        return message["content"]

    def decide(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
    ) -> Message:
        payload: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "stream": False,
            "enable_thinking": False,
        }
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            self.request_count += 1
            response = self.http.post(
                f"{self.settings.base_url.rstrip('/')}/chat/completions",
                json=payload,
                timeout=self.settings.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds,
            )
        except httpx.TimeoutException:
            raise ModelError(
                "模型请求超时，请稍后重试或调整 LLM_TIMEOUT_SECONDS。", "timeout"
            ) from None
        except httpx.RequestError:
            raise ModelError("无法连接模型服务：请检查网络与 LLM_BASE_URL。", "network") from None
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
            code = {401: "authentication", 403: "authentication", 429: "rate_limit"}.get(
                response.status_code, "api_error"
            )
            raise ModelError(hint, code)
        try:
            if not response.content.strip():
                raise ModelError(
                    "模型协议错误：响应为空，未返回有效的完整文本回答。", "empty_response"
                )
            choices = response.json()["choices"]
            if choices == []:
                raise ModelError(
                    "模型协议错误：响应为空，未返回有效的完整文本回答。", "empty_response"
                )
            choice = choices[0]
            message = choice["message"]
            content = message.get("content")
            calls = message.get("tool_calls")
            if choice.get("finish_reason") not in {"stop", "tool_calls"}:
                raise ValueError
            if message.get("role") != "assistant":
                raise ValueError
            if content is not None and not isinstance(content, str):
                raise ValueError
            result: Message = {"role": "assistant", "content": content}
            if calls is not None and not isinstance(calls, list):
                raise ValueError
            if calls:
                ids: set[str] = set()
                normalized = []
                for call in calls:
                    call_id = call["id"]
                    function = call["function"]
                    name, arguments = function["name"], function["arguments"]
                    if (
                        call.get("type") != "function"
                        or not isinstance(call_id, str)
                        or not call_id.strip()
                        or call_id in ids
                        or not isinstance(name, str)
                        or not name.strip()
                        or not isinstance(arguments, str)
                    ):
                        raise ValueError
                    ids.add(call_id)
                    normalized.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    )
                result["tool_calls"] = normalized
            elif not isinstance(content, str) or not content.strip():
                raise ModelError("模型协议错误：未返回有效的完整文本回答。", "empty_response")
            return result
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ModelError(
                "模型协议错误：未返回有效的完整文本回答或工具调用。", "protocol_error"
            ) from None
