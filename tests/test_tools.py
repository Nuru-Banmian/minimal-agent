import json

import pytest
from jsonschema import SchemaError

from minimal_agent.tools import ToolRegistry, calculator, calculator_registry


def test_registry_rejects_duplicate_names_and_invalid_schemas():
    registry = calculator_registry()
    with pytest.raises(ValueError, match="重复"):
        registry.register("calculator", "duplicate", {"type": "object"}, calculator)
    with pytest.raises(SchemaError):
        registry.register("broken", "invalid schema", {"type": "not-a-type"}, calculator)
    assert len(registry.definitions()) == 1


def test_registry_exposes_schema_and_validates_before_execution():
    registry = ToolRegistry()
    calls = []
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    registry.register("capture", "测试执行边界", schema, lambda value: calls.append(value))
    schema["required"].clear()
    exposed = registry.definitions()
    assert exposed == [
        {
            "type": "function",
            "function": {
                "name": "capture",
                "description": "测试执行边界",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    exposed[0]["function"]["parameters"]["required"].clear()
    assert registry.execute("capture", "{}")["status"] == "error"
    assert calls == []
    assert registry.execute("capture", '{"value":7}')["status"] == "ok"
    assert calls == [7]


@pytest.mark.parametrize(
    "operation,a,b,expected",
    [
        ("add", 12, 8, 20),
        ("subtract", 3, 8, -5),
        ("multiply", 20, 3, 60),
        ("divide", 3, 2, 1.5),
    ],
)
def test_real_calculator_through_registry(operation, a, b, expected):
    assert calculator_registry().execute(
        "calculator",
        json.dumps(
            {
                "operation": operation,
                "a": a,
                "b": b,
            }
        ),
    ) == {"status": "ok", "result": expected}
