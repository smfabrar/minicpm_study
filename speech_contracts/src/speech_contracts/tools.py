"""Validation and Granite schema shape for serialized tool definitions."""
import re


def validate_definition(tool):
    for key in ("name", "parameter"):
        if not isinstance(tool.get(key), str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,63}", tool[key]):
            raise ValueError(f"{key} must be a valid function identifier")
    if not isinstance(tool.get("description"), str) or not tool["description"].strip():
        raise ValueError("Tool description cannot be empty")
    if tool.get("kind") not in {"room", "document", "calculator", "fixture"}:
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


def function_schema(tool: dict) -> dict:
    validate_definition(tool)
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": {
                "type": "object",
                "properties": {
                    tool["parameter"]: {
                        "type": "string",
                        "description": "Detail explicitly present in the user request",
                    },
                },
                "required": [tool["parameter"]],
                "additionalProperties": False,
            },
        },
    }
