import socket

import pytest

from minimal_agent.client import ModelClient, ModelError
from minimal_agent.config import Settings


def test_client_sends_configured_non_streaming_chat(model_server):
    model_server.answer("你好，小林！")
    settings = Settings(model="qwen-plus", base_url=model_server.url, api_key="test-key")
    messages = [{"role": "user", "content": "我叫小林"}]
    with ModelClient(settings) as client:
        assert client.complete(messages) == "你好，小林！"

    request = model_server.requests.get_nowait()
    assert request["path"] == "/compatible-mode/v1/chat/completions"
    assert request["authorization"] == "Bearer test-key"
    assert request["body"] == {
        "model": "qwen-plus",
        "messages": messages,
        "stream": False,
        "enable_thinking": False,
    }


@pytest.mark.parametrize(
    ("status", "hint"),
    [
        (401, "鉴权失败"),
        (403, "权限不足"),
        (429, "请求过多"),
        (500, "服务暂时不可用"),
        (400, "模型名称"),
    ],
)
def test_client_reports_safe_http_errors(model_server, status, hint):
    model_server.replies.put((status, {"error": {"message": "secret-key PRIVATE detail"}}))
    with ModelClient(Settings("qwen-plus", model_server.url, "secret-key")) as client:
        with pytest.raises(ModelError, match=hint) as error:
            client.complete([{"role": "user", "content": "你好"}])
    assert "secret-key" not in str(error.value)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"role": "assistant", "content": None}}]},
        {"choices": [{"message": {"role": "assistant", "content": " "}}]},
        {"choices": [{"message": {"role": "assistant", "content": 123}}]},
        {"choices": [{"message": {"role": "user", "content": "错误角色"}}]},
        {
            "choices": [
                {"message": {"role": "assistant", "content": "部分答案"}, "finish_reason": "length"}
            ]
        },
        {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "调用工具", "tool_calls": [{}]},
                    "finish_reason": "tool_calls",
                }
            ]
        },
    ],
)
def test_client_rejects_invalid_or_incomplete_answers(model_server, payload):
    model_server.replies.put((200, payload))
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key")) as client:
        with pytest.raises(ModelError, match="有效的完整文本回答"):
            client.complete([{"role": "user", "content": "你好"}])


def test_client_reports_timeout(model_server):
    model_server.delay = 0.15
    model_server.answer("太晚的回答")
    with ModelClient(Settings("qwen-plus", model_server.url, "test-key", 0.02)) as client:
        with pytest.raises(ModelError, match="超时"):
            client.complete([{"role": "user", "content": "你好"}])


def test_client_reports_connection_failure():
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{reserved.getsockname()[1]}/v1"
        with ModelClient(Settings("qwen-plus", url, "test-key", 3.0)) as client:
            with pytest.raises(ModelError, match="连接"):
                client.complete([{"role": "user", "content": "你好"}])
