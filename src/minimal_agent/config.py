import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


class ConfigError(Exception):
    """An actionable configuration error that never contains configuration values."""


@dataclass(frozen=True)
class Settings:
    model: str
    base_url: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ConfigError("缺少配置 LLM_MODEL，例如 qwen-plus。")
        if not self.api_key or any(ord(char) < 33 or ord(char) > 126 for char in self.api_key):
            raise ConfigError("DASHSCOPE_API_KEY 缺失或格式无效，请设置真实 API key。")
        try:
            url = urlsplit(self.base_url)
            valid_url = (
                url.scheme in {"https", "http"}
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
                and all(not c.isspace() and c not in "{}" for c in self.base_url)
                and not url.path.rstrip("/").endswith("/chat/completions")
            )
            _ = url.port  # Parsing the port also validates its format and range.
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ConfigError(
                "LLM_BASE_URL 无效：请填写所属地域的完整 API base URL，"
                "替换业务空间占位符，不含凭据、查询参数或 /chat/completions。"
            )
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ConfigError("LLM_TIMEOUT_SECONDS 必须是大于 0 的有限秒数。")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path.cwd() / ".env", override=False, encoding="utf-8-sig", interpolate=False)
        names = ("LLM_MODEL", "LLM_BASE_URL", "DASHSCOPE_API_KEY")
        missing = [name for name in names if not os.environ.get(name, "").strip()]
        if missing:
            raise ConfigError("缺少配置：" + "、".join(missing) + "。请按 README 设置环境变量。")
        try:
            timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
        except ValueError:
            raise ConfigError("LLM_TIMEOUT_SECONDS 必须是大于 0 的有限秒数。") from None
        return cls(
            model=os.environ["LLM_MODEL"].strip(),
            base_url=os.environ["LLM_BASE_URL"].strip(),
            api_key=os.environ["DASHSCOPE_API_KEY"].strip(),
            timeout_seconds=timeout,
        )
