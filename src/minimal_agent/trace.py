"""Bounded, secret-safe trace records for console and local JSONL."""

import json
import re
from pathlib import Path
from typing import Any


class TraceError(Exception):
    """The trace could not be recorded."""


def safe_event(event: dict[str, Any], secrets: tuple[str, ...]) -> dict[str, Any]:
    def redact(text: str) -> str:
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        text = re.sub(r"(?i)bearer\s+[^\s\"',}]+", "Bearer [REDACTED]", text)
        text = re.sub(
            r"(?i)(authorization\s*[\"']?\s*[:=]\s*[\"']?)[^\r\n\"',}]+",
            r"\1[REDACTED]",
            text,
        )
        return re.sub(
            r"(?i)(bearer\s+|(?:api[_-]?key|authorization)\s*[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+",
            r"\1[REDACTED]",
            text,
        )

    def clean(value: Any, depth: int = 0) -> Any:
        if depth > 12:
            return "[DEPTH LIMIT]"
        if isinstance(value, str):
            # Arguments can themselves contain encoded JSON with credential fields.
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                return redact(value)
            if isinstance(parsed, (dict, list)):
                return json.dumps(clean(parsed, depth + 1), ensure_ascii=False)
            return redact(value)
        if isinstance(value, dict):
            return {
                redact(str(k)): "[REDACTED]"
                if re.search(r"(?i)api[_-]?key|authorization|token|secret|password", str(k))
                else clean(v, depth + 1)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [clean(v, depth + 1) for v in value]
        return value

    output = {}
    for key, value in event.items():
        sanitized = clean(value)
        encoded = json.dumps(sanitized, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 2048:
            sanitized = {
                "truncated": True,
                "original_bytes": len(encoded),
                "preview": encoded[:2048].decode("utf-8", errors="ignore"),
            }
        output[key] = sanitized
    return output


class JsonlTrace:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        except OSError:
            raise TraceError(
                "执行日志写入失败，请检查 --trace-file 路径、权限与磁盘空间。"
            ) from None
