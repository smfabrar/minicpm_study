"""Native generation boundary fixtures; these do not measure Granite quality."""

import asyncio
from unittest.mock import Mock

import pytest

from fixtures import default_tools
from tool_pipeline.models.granite import GraniteCaller
from tool_pipeline.telemetry import TraceRecorder
from tool_pipeline.tools import ToolRegistry


def caller_with_output(raw):
    caller = GraniteCaller.__new__(GraniteCaller)
    caller.registry = ToolRegistry(default_tools(), TraceRecorder())
    caller.trace = TraceRecorder()
    # Reproduce the recorded classifier's tendency to choose clarification.
    # Only GPU generation is substituted; parsing and dispatch stay real.
    caller._score_routes = lambda transcript, options: {
        label: (-0.2 if action == "clarify" else -7.0)
        for label, _, action in options
    }
    caller.generate = Mock(return_value=raw)
    return caller


def test_complete_request_generates_one_native_call_with_all_schemas():
    caller = caller_with_output(
        '<tool_call>\n{"name":"calculator","arguments":{"expression":"17 times 23"}}\n'
        '</tool_call><|end_of_text|>'
    )
    action = asyncio.run(caller.decide("What is 17 times 23?"))
    assert action["kind"] == "call"
    assert action["tool"] == "calculator"
    assert action["arguments"] == {"expression": "17 times 23"}
    assert caller.generate.call_count == 1
    messages, schemas = caller.generate.call_args.args
    assert {schema["function"]["name"] for schema in schemas} == {
        "room_lookup", "calculator", "document_search"
    }
    assert messages[-1] == {"role": "user", "content": "What is 17 times 23?"}
    result = asyncio.run(caller.registry.execute(action["tool"], action["arguments"], messages[-1]["content"]))
    assert "391" in result["facts"]


@pytest.mark.parametrize("reply", ["Hello!", "Which seminar do you mean?", "391"])
def test_native_plain_reply_is_returned_for_response_delivery(reply):
    caller = caller_with_output(reply + "<|end_of_text|>")
    action = caller.route("Can you help me?")
    assert action["kind"] == "respond"
    assert action["message"] == reply
    assert action["raw"] == reply + "<|end_of_text|>"


@pytest.mark.parametrize("raw", [
    "",
    "<|end_of_text|>",
    "<tool_call",
    "</tool_call",
    '{"name":"calculator","arguments":{"expression":"2+2"}',
    '[{"name":"calculator",',
    '<tool_call>{"name":"calculator","arguments":',
    '<tool_call>{"name":"calculator","arguments":[]}</tool_call>',
    'Sure. <tool_call>{"name":"calculator","arguments":{"expression":"2+2"}}</tool_call>',
    '<tool_call>{"name":"calculator","arguments":{"expression":"2+2"}}</tool_call>'
    '<tool_call>{"name":"calculator","arguments":{"expression":"3+3"}}</tool_call>',
    '<tool_call><function=calculator><parameter=expression>2+2</parameter></function></tool_call>',
    '<tool_call>{"name":"unknown_function","arguments":{}}</tool_call>',
])
def test_empty_malformed_multiple_and_unknown_calls_are_not_spoken_as_replies(raw):
    action = caller_with_output(raw).route("What is two plus two?")
    assert action["kind"] == "invalid"
    assert action["message"]
    assert action["raw"] == raw
