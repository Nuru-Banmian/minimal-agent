import json
import math
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


class ToolRegistry:
    """Validate definitions at registration, arguments before dispatch."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[dict[str, Any], Callable[..., Any]]] = {}

    def register(
        self, name: str, description: str, schema: dict[str, Any], execute: Callable[..., Any]
    ) -> None:
        if not name.strip() or name in self._tools:
            raise ValueError("工具名称为空或重复")
        if not description.strip() or not callable(execute):
            raise ValueError("工具需要描述和执行函数")
        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object":
            raise ValueError("工具参数 Schema 必须是 object")
        self._tools[name] = (
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": deepcopy(schema),
                },
            },
            execute,
        )

    def definitions(self) -> list[dict[str, Any]]:
        return [deepcopy(definition) for definition, _ in self._tools.values()]

    def execute(self, name: str, arguments: str) -> dict[str, Any]:
        if name not in self._tools:
            return {"status": "error", "error": "unknown_tool"}
        definition, execute = self._tools[name]
        try:
            params = json.loads(arguments, parse_constant=_reject_constant)
            Draft202012Validator(definition["function"]["parameters"]).validate(params)
        except (ValueError, ValidationError, OverflowError, RecursionError):
            return {"status": "error", "error": "invalid_arguments"}
        try:
            result = execute(**params)
        except (ValueError, OverflowError, ZeroDivisionError):
            return {"status": "error", "error": "invalid_calculation"}
        return {"status": "ok", "result": result}


def _reject_constant(value: str) -> None:
    raise ValueError("非法 JSON 数值")


def calculator(operation: str, a: float, b: float) -> float:
    if isinstance(a, bool) or isinstance(b, bool) or not math.isfinite(a) or not math.isfinite(b):
        raise ValueError("参数必须是有限数值")
    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "divide":
        result = a / b
    else:
        raise ValueError("未知运算")
    if not math.isfinite(result):
        raise ValueError("结果必须是有限数值")
    return result


def calculator_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        "calculator",
        "执行一次加减乘除；复杂计算可连续调用。",
        {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
                "a": {"type": "number", "description": "左操作数"},
                "b": {"type": "number", "description": "右操作数"},
            },
            "required": ["operation", "a", "b"],
            "additionalProperties": False,
        },
        calculator,
    )
    return registry
