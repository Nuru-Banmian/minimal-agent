"""Explicitly opt in; this test never substitutes a scripted model for the real API."""

import os
from datetime import UTC, datetime

import pytest

from minimal_agent.client import Message, ModelClient
from minimal_agent.config import Settings


@pytest.mark.skipif(os.environ.get("RUN_LIVE_API") != "1", reason="真实 API 验证未显式开启")
def test_real_api_remembers_name():
    settings = Settings.from_env()
    assert settings.base_url.startswith("https://"), "真实验收要求配置 HTTPS 模型服务"
    messages: list[Message] = [
        {"role": "system", "content": "请用中文简短回答。"},
        {"role": "user", "content": "我叫小林"},
    ]
    with ModelClient(settings) as client:
        first = client.complete(messages)
        messages.extend(
            [
                {"role": "assistant", "content": first},
                {"role": "user", "content": "我叫什么？只回答我的名字。"},
            ]
        )
        second = client.complete(messages)
    assert "小林" in second, "真实模型未正确回答名字（不输出原始服务响应）"
    print(f"真实 API: {datetime.now(UTC).isoformat()} model={settings.model}; 两轮成功，名字匹配")
