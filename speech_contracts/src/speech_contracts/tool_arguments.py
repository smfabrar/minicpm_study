"""The JSON Schema subset used by tool callers: objects, arrays and scalar values."""

import json
import math
import re

_TYPES = {"object": dict, "array": list, "string": str, "integer": int,
          "number": (int, float), "boolean": bool, "null": type(None)}
_KEYWORDS = {"type", "description", "title", "properties", "required", "additionalProperties",
             "items", "enum", "const", "default", "minimum", "maximum", "minLength",
             "maxLength", "minItems", "maxItems", "pattern"}


def validate_parameters(schema: dict, *, root=True, depth=0) -> None:
    if depth > 12 or not isinstance(schema, dict):
        raise ValueError("Parameter schema must be an object with at most 12 nesting levels")
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise ValueError(f"Unsupported parameter schema keywords: {', '.join(sorted(unknown))}")
    kind = schema.get("type")
    if not isinstance(kind, str) or kind not in _TYPES or (root and kind != "object"):
        raise ValueError("Each parameter schema needs a type; the root must be object")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ValueError("enum must be a non-empty array")
    for field in ("description", "title", "pattern"):
        if field in schema and not isinstance(schema[field], str):
            raise ValueError(f"{field} must be text")
    for field in ("minLength", "maxLength", "minItems", "maxItems"):
        if field in schema and (type(schema[field]) is not int or schema[field] < 0):
            raise ValueError(f"{field} must be a non-negative integer")
    for field in ("minimum", "maximum"):
        if field in schema and (type(schema[field]) not in (int, float) or not math.isfinite(schema[field])):
            raise ValueError(f"{field} must be a finite number")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise ValueError(f"Invalid schema pattern: {exc}") from exc
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or any(not isinstance(key, str) for key in properties):
            raise ValueError("properties must map names to parameter schemas")
        if not isinstance(required, list) or any(not isinstance(key, str) or key not in properties for key in required):
            raise ValueError("required must list declared property names")
        if type(schema.get("additionalProperties", False)) is not bool:
            raise ValueError("additionalProperties must be true or false")
        for child in properties.values():
            validate_parameters(child, root=False, depth=depth + 1)
    if kind == "array":
        validate_parameters(schema.get("items"), root=False, depth=depth + 1)


def validate_arguments(arguments: dict, schema: dict) -> dict:
    """Validate without coercion or insertion of defaults; return the original values."""
    validate_parameters(schema)
    try:
        encoded = json.dumps(arguments, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tool arguments must be finite JSON values") from exc
    if len(encoded.encode()) > 16384:
        raise ValueError("Tool arguments exceed 16 KiB")
    _validate(arguments, schema, "arguments")
    return arguments


def _validate(value, schema, path):
    kind = schema["type"]
    if not isinstance(value, _TYPES[kind]) or (kind in {"integer", "number"} and isinstance(value, bool)):
        raise ValueError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} must be one of {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if kind == "object":
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        extra = set(value) - set(properties)
        if missing or (extra and not schema.get("additionalProperties", False)):
            raise ValueError(f"{path}: missing keys {sorted(missing)}, unknown keys {sorted(extra)}")
        for key in value.keys() & properties.keys():
            _validate(value[key], properties[key], f"{path}.{key}")
    elif kind == "array":
        for index, item in enumerate(value):
            _validate(item, schema["items"], f"{path}[{index}]")
    if kind in {"string", "array"}:
        suffix = "Length" if kind == "string" else "Items"
        if len(value) < schema.get("min" + suffix, 0) or len(value) > schema.get("max" + suffix, 16384):
            raise ValueError(f"{path} has an invalid length")
        if kind == "string" and "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ValueError(f"{path} does not match the required pattern")
    if kind in {"number", "integer"} and not schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf):
        raise ValueError(f"{path} is outside the allowed range")
