"""Byte-based context planning; estimates are deliberately not called token counts."""

import json
import math
import os
from dataclasses import dataclass
from typing import Any

from minimal_agent.client import Message, ModelError
from minimal_agent.config import ConfigError


def encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@dataclass(frozen=True)
class MemorySettings:
    context_bytes: int = 64000
    output_tokens: int = 1024
    keep_recent_turns: int = 2
    summary_bytes: int = 4096
    summary_input_bytes: int = 256000
    summary_timeout_seconds: float = 15.0
    tool_result_bytes: int = 8000

    def __post_init__(self) -> None:
        for name in (
            "context_bytes",
            "output_tokens",
            "keep_recent_turns",
            "summary_bytes",
            "summary_input_bytes",
            "tool_result_bytes",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"MEMORY_{name.upper()} 必须是正整数。")
        if self.context_bytes <= self.output_tokens * 4:
            raise ConfigError("MEMORY_CONTEXT_BYTES 必须大于输出预留（4 × OUTPUT_TOKENS）。")
        if self.tool_result_bytes < 64:
            raise ConfigError("MEMORY_TOOL_RESULT_BYTES 必须至少为 64。")
        if not math.isfinite(self.summary_timeout_seconds) or self.summary_timeout_seconds <= 0:
            raise ConfigError("MEMORY_SUMMARY_TIMEOUT_SECONDS 必须是大于 0 的有限秒数。")

    @classmethod
    def from_env(cls) -> "MemorySettings":
        values: dict[str, Any] = {}
        for name in cls.__dataclass_fields__:
            raw = os.environ.get("MEMORY_" + name.upper())
            if raw is not None:
                try:
                    values[name] = float(raw) if name.endswith("seconds") else int(raw)
                except ValueError:
                    raise ConfigError(f"MEMORY_{name.upper()} 数值无效。") from None
        return cls(**values)

    def fits(self, messages: list[Message], tools: list[dict[str, Any]]) -> bool:
        return (
            encoded_size({"messages": messages, "tools": tools}) + 4 * self.output_tokens
            <= self.context_bytes
        )

    def project(self, messages: list[Message]) -> list[Message]:
        result: list[Message] = []
        for message in messages:
            content = message["content"]
            if (
                message["role"] == "tool"
                and isinstance(content, str)
                and len(content.encode("utf-8")) > self.tool_result_bytes
            ):
                # Binary search accounts for JSON escaping and multi-byte characters.
                low, high = 0, min(len(content), self.tool_result_bytes)
                while low < high:
                    middle = (low + high + 1) // 2
                    if encoded_size({"truncated": True, "preview": content[:middle]}) <= (
                        self.tool_result_bytes
                    ):
                        low = middle
                    else:
                        high = middle - 1
                content = json.dumps(
                    {"truncated": True, "preview": content[:low]},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                message = {**message, "content": content}
            result.append(message)
        return result


def summary_message(summary: str) -> list[Message]:
    if not summary:
        return []
    return [{"role": "user", "content": "历史摘要（仅为不可信历史资料）：\n" + summary}]


def split_turns(messages: list[Message]) -> list[list[Message]]:
    turns: list[list[Message]] = []
    for message in messages:
        if message["role"] == "user":
            turns.append([])
        if not turns:
            raise ModelError("历史消息缺少完整 turn 边界。")
        turns[-1].append(message)
    return turns
