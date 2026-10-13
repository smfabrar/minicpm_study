"""Validation and Granite schema shape for serialized tool definitions."""
import ast
import re

from .tool_arguments import validate_parameters


def validate_definition(tool):
    for key in ("name", "parameter"):
        if not isinstance(tool.get(key), str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", tool[key]):
            raise ValueError(f"{key} must be a valid function identifier")
    if not isinstance(tool.get("description"), str) or not tool["description"].strip():
        raise ValueError("Tool description cannot be empty")
    if tool.get("kind") not in {"room", "document", "calculator", "fixture", "python"}:
        raise ValueError("Unknown tool implementation")
    delay = tool.get("delay_ms", 0)
    if type(delay) not in (int, float) or not 0 <= delay <= 60000:
        raise ValueError("Tool delay must be between 0 and 60000 ms")
    for field in ("records", "aliases"):
        data = tool.get(field, {})
        if not isinstance(data, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.items()):
            raise ValueError(f"{field} must map text keys to text values")
    if tool.get("failure", "none") not in {"none", "error", "empty"}:
        raise ValueError("Unknown failure policy")

    if tool.get("kind") == "python":
        source = tool.get("python_code", "")
        if not isinstance(source, str) or not source.strip() or len(source) > 65536:
            raise ValueError("Python source must contain 1–65536 characters")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise ValueError(f"Invalid Python source: {exc}") from exc
        if not any(isinstance(node, ast.FunctionDef) and node.name == "execute" for node in tree.body):
            raise ValueError("Python tools must define def execute(arguments)")
        if tool.get("parameters") is None:
            raise ValueError("Python tools need a parameters schema (use an empty object for no arguments)")
    if tool.get("parameters") is not None:
        validate_parameters(tool["parameters"])
        if tool["kind"] != "python":
            raise ValueError("Custom parameter schemas are supported by Python tools; fixtures use their string parameter")
    timeout = tool.get("timeout_seconds", 10)
    if type(timeout) not in (int, float) or not 0 < timeout <= 120:
        raise ValueError("Tool timeout must be greater than 0 and at most 120 seconds")
    if type(tool.get("ground_arguments", True)) is not bool:
        raise ValueError("ground_arguments must be true or false")


def function_schema(tool: dict) -> dict:
    validate_definition(tool)
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool.get("parameters") or {
                "type": "object",
                "properties": {
                    tool["parameter"]: {
                        "type": "string", "minLength": 1, "maxLength": 240,
                        "description": "Detail explicitly present in the user request",
                    },
                },
                "required": [tool["parameter"]],
                "additionalProperties": False,
            },
        },
    }
