import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from minimal_agent.config import ConfigError


def search(query: str) -> dict[str, Any]:
    """Search a fixed teaching fixture, never the network or today's weather."""
    document = {
        "title": "上海示例天气（2026-09-01）",
        "source": "mock:weather:shanghai:2026-09-01",
        "content": "2026-09-01 上海：小雨，22–27°C，出门建议带伞。仅为模拟示例，非实时天气。",
        "mock": True,
    }
    terms = query.lower().split()
    searchable = f"{document['title']} {document['content']} 上海天气 shanghai weather"
    matches = [document] if terms and all(term in searchable for term in terms) else []
    return {
        "mock": True,
        "notice": "模拟资料，非实时信息。" if matches else "无命中；模拟资料库无匹配结果。",
        "matches": matches,
    }


class SearchError(Exception):
    """A fixed public error code, never a provider response or credential."""


@dataclass
class TavilySearch:
    api_key: str = field(repr=False)
    transport: httpx.BaseTransport | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ConfigError("联网搜索需要有效的 TAVILY_API_KEY，请在本地 .env 配置。")

    def __call__(self, query: str) -> dict[str, Any]:
        if not query.strip() or len(query) > 500:
            raise SearchError("search_invalid_query")
        try:
            with httpx.Client(timeout=10, trust_env=False, transport=self.transport) as client:
                with client.stream(
                    "POST",
                    "https://api.tavily.com/search",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "max_results": 5,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                ) as response:
                    if response.status_code != 200:
                        code = {
                            401: "search_authentication_failed",
                            403: "search_authentication_failed",
                            429: "search_rate_limited",
                            432: "search_quota_exceeded",
                            433: "search_quota_exceeded",
                        }.get(response.status_code, "search_unavailable")
                        raise SearchError(code)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 1_000_000:
                            raise SearchError("search_response_too_large")
                    payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ValueError
            results = payload["results"]
            matches = []
            for row in results[:5]:
                if not isinstance(row, dict) or any(
                    not isinstance(row.get(key), str) for key in ("title", "url", "content")
                ):
                    raise ValueError
                url = urlsplit(row["url"])
                if (
                    url.scheme not in {"http", "https"}
                    or not url.hostname
                    or url.username is not None
                    or url.password is not None
                    or any(c.isspace() for c in row["url"])
                    or len(row["url"]) > 2048
                ):
                    raise ValueError
                matches.append(
                    {
                        "title": row["title"][:300],
                        "source": row["url"],
                        "content": row["content"][:2000],
                        "mock": False,
                        "truncated": len(row["title"]) > 300 or len(row["content"]) > 2000,
                    }
                )
        except httpx.TimeoutException:
            raise SearchError("search_timeout") from None
        except httpx.HTTPError:
            raise SearchError("search_unavailable") from None
        except (ValueError, RecursionError):
            raise SearchError("search_invalid_response") from None
        return {
            "mock": False,
            "notice": (
                "联网搜索摘要，不保证网页内容实时；引用来源并核对资料日期。"
                if matches
                else "无命中；联网搜索没有返回匹配结果。"
            ),
            "matches": matches,
            "truncated": len(results) > 5,
        }
