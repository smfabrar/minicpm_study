import asyncio
import tempfile
import unittest
from pathlib import Path

from tool_pipeline.telemetry import TraceRecorder
from tool_pipeline.tools import ToolRegistry
from fixtures import default_tools
from speech_contracts import RunRequest


class TraceTests(unittest.TestCase):
    def test_nested_spans_retain_parent_and_error(self):
        trace = TraceRecorder()
        with trace.span("pipeline") as parent:
            with self.assertRaises(ValueError):
                with trace.span("tool"):
                    raise ValueError("unknown room")
        spans = trace.snapshot()["spans"]
        child = next(s for s in spans if s["name"] == "tool")
        self.assertEqual(child["parent_id"], parent.id)
        self.assertEqual(child["status"], "error")
        self.assertGreaterEqual(child["duration_ns"], 0)
        self.assertIn("unknown room", child["attributes"]["error"])

    def test_parallel_work_does_not_inherit_other_tasks_span(self):
        trace = TraceRecorder()
        async def work(name):
            with trace.span(name):
                await asyncio.sleep(0.001)
                with trace.span(name + ".child"):
                    pass
        asyncio.run(self._parallel(work))
        spans = {s["name"]: s for s in trace.snapshot()["spans"]}
        self.assertEqual(spans["a.child"]["parent_id"], spans["a"]["id"])
        self.assertEqual(spans["b.child"]["parent_id"], spans["b"]["id"])

    async def _parallel(self, work):
        await asyncio.gather(work("a"), work("b"))


class ToolTests(unittest.TestCase):
    def test_calculator_evaluates_arithmetic_without_code_execution(self):
        registry = ToolRegistry(default_tools(), TraceRecorder())
        result = asyncio.run(registry.execute("calculator", {"expression": "17 times 23"}, "What is 17 times 23?"))
        self.assertIn("391", result["facts"])
        with self.assertRaises(ValueError):
            asyncio.run(registry.execute("calculator", {"expression": "__import__('os')"}, "arithmetic"))

    def test_ungrounded_room_name_never_executes(self):
        registry = ToolRegistry(default_tools(), TraceRecorder())
        with self.assertRaisesRegex(ValueError, "grounded"):
            asyncio.run(registry.execute("room_lookup", {"name": "robotics seminar"}, "Where is the seminar?"))

    def test_custom_fixture_tool_has_native_granite_schema(self):
        registry = ToolRegistry([{"name": "stock_lookup", "description": "Look up stock", "parameter": "item", "kind": "fixture", "records": {"pencil": "12 pencils"}, "delay_ms": 0}], TraceRecorder())
        self.assertEqual(registry.schemas[0]["function"]["parameters"]["required"], ["item"])
        result = asyncio.run(registry.execute("stock_lookup", {"item": "pencil"}, "How many pencil items?"))
        self.assertEqual(result["facts"], "12 pencils")

    def test_unknown_tool_and_extra_arguments_are_rejected(self):
        registry = ToolRegistry(default_tools(), TraceRecorder())
        for name, args in [("unknown", {"name": "x"}), ("room_lookup", {"name": "x", "extra": "y"})]:
            with self.assertRaises(ValueError):
                asyncio.run(registry.execute(name, args, "x"))

    def test_request_rejects_invalid_condition_and_missing_b2_fact(self):
        with self.assertRaises(ValueError):
            RunRequest.from_dict({"condition": "B3", "audio_path": "x.wav"})
        with self.assertRaises(ValueError):
            RunRequest.from_dict({"condition": "B2", "audio_path": "x.wav", "oracle_result": ""})
