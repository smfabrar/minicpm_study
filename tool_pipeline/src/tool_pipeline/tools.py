"""Granite-compatible bounded tools, backed by frozen data."""

import asyncio
import re

from speech_contracts import function_schema, validate_definition, validate_arguments
from .reference import reference_module
from .python_tool import PythonToolExecutor


def string_arguments(value, path="arguments"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from string_arguments(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from string_arguments(item, f"{path}[{index}]")


class ToolRegistry:
    def __init__(self, definitions, trace, output_dir=None):
        self.trace = trace
        self.python = PythonToolExecutor(output_dir, trace)
        self.definitions = {}
        for tool in definitions:
            validate_definition(tool)
            if tool["name"] in self.definitions:
                raise ValueError("Duplicate tool name")
            self.definitions[tool["name"]] = tool
        self.schemas = [function_schema(tool) for tool in self.definitions.values()]

    async def execute(self, name, arguments, transcript):
        with self.trace.span("controller.validate", tool=name, raw_arguments=arguments):
            if name not in self.definitions:
                raise ValueError("Tool is not allowlisted")
            tool = self.definitions[name]
            schema = next(s["function"]["parameters"] for s in self.schemas if s["function"]["name"] == name)
            args = validate_arguments(arguments, schema)
            if tool["kind"] != "python":
                args = {key: value.strip() for key, value in args.items()}
                if not args[tool["parameter"]]:
                    raise ValueError("Tool argument cannot be blank")
            if tool["kind"] != "calculator" and tool.get("ground_arguments", True):
                heard = " ".join(re.findall(r"[a-z0-9]+", transcript.casefold()))
                for key, value in string_arguments(args):
                    proposed = " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
                    if not proposed or proposed not in heard:
                        raise ValueError(f"Tool argument {key} is not grounded in the committed transcript")
        with self.trace.span("controller.normalize", raw_arguments=args) as span:
            canonical_args = dict(args)
            if tool["kind"] == "calculator":
                canonical_args[tool["parameter"]] = reference_module("tools").normalize_calculator_expression(args[tool["parameter"]])
            span.attributes["arguments"] = canonical_args
        if tool.get("delay_ms", 0):
            with self.trace.span("tool.configured_delay", tool=name, configured_ms=tool["delay_ms"]):
                await asyncio.sleep(tool["delay_ms"] / 1000)
        with self.trace.span("tool.execute", tool=name, arguments=canonical_args):
            if tool.get("failure") == "error":
                raise RuntimeError("Configured tool failure")
            if tool.get("failure") == "empty":
                raise LookupError("Configured empty result")
            if tool["kind"] == "python":
                result = await self.python.execute(tool, canonical_args)
                return {**result, "raw_arguments": arguments, "arguments": canonical_args}
            canonical = canonical_args[tool["parameter"]]
            module = reference_module("tools")
            if tool["kind"] == "calculator":
                result = await module.SafeCalculator()({"expression": canonical})
            elif tool["kind"] == "document":
                result = await module.DocumentSearch(tool.get("records", {}))({"query": canonical})
            else:
                lookup = module.RoomLookup(tool.get("records", {}), aliases=tool.get("aliases", {}))
                result = await lookup({"name": canonical})
            return {"facts": result.facts, "sources": list(result.sources), "raw_arguments": arguments,
                    "arguments": canonical_args}
