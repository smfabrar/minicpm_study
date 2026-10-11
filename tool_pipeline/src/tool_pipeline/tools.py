"""Granite-compatible bounded tools, backed by frozen data."""

import asyncio
import re

from speech_contracts import function_schema, validate_definition
from .reference import reference_module


class ToolRegistry:
    def __init__(self, definitions, trace):
        self.trace = trace
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
            args = reference_module("tools").validate_call(name, arguments, self.schemas)
            raw = args[tool["parameter"]]
            heard = " ".join(re.findall(r"[a-z0-9]+", transcript.casefold()))
            proposed = " ".join(re.findall(r"[a-z0-9]+", raw.casefold()))
            if tool["kind"] != "calculator" and (not proposed or proposed not in heard):
                raise ValueError("Tool argument is not grounded in the committed transcript")
        with self.trace.span("controller.normalize", raw_arguments=args) as span:
            canonical = reference_module("tools").normalize_calculator_expression(raw) if tool["kind"] == "calculator" else raw
            span.attributes["arguments"] = {tool["parameter"]: canonical}
        if tool.get("delay_ms", 0):
            with self.trace.span("tool.configured_delay", tool=name, configured_ms=tool["delay_ms"]):
                await asyncio.sleep(tool["delay_ms"] / 1000)
        with self.trace.span("tool.execute", tool=name, arguments={tool["parameter"]: canonical}):
            if tool.get("failure") == "error":
                raise RuntimeError("Configured tool failure")
            if tool.get("failure") == "empty":
                raise LookupError("Configured empty result")
            module = reference_module("tools")
            if tool["kind"] == "calculator":
                result = await module.SafeCalculator()({"expression": canonical})
            elif tool["kind"] == "document":
                result = await module.DocumentSearch(tool.get("records", {}))({"query": canonical})
            else:
                lookup = module.RoomLookup(tool.get("records", {}), aliases=tool.get("aliases", {}))
                result = await lookup({"name": canonical})
            return {"facts": result.facts, "sources": list(result.sources), "raw_arguments": arguments,
                    "arguments": {tool["parameter"]: canonical}}
