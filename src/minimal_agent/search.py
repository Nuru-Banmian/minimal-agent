from typing import Any


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
