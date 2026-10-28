"""Qwen3 tool calls using its native template with thinking disabled."""

import json
import re

from ..reference import reference_module
from .caller import NativeToolCaller


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


class QwenCaller(NativeToolCaller):
    family = "qwen3"
    template_options = {"enable_thinking": False}
    end_tokens = ("<|im_end|>", "<|endoftext|>")

    def parse_output(self, message):
        action_type = reference_module("contracts").CallerAction
        if message.startswith("{"):
            try:
                data = json.loads(message, object_pairs_hook=_unique_object)
            except ValueError:
                return action_type("invalid", message="Malformed or ambiguous JSON tool call")
            if (set(data) == {"name", "arguments"} and isinstance(data["name"], str)
                    and isinstance(data["arguments"], dict)):
                return action_type("call", tool=data["name"], arguments=data["arguments"])
            return action_type("invalid", message="Expected one tool name and arguments object")
        if not message.startswith("<tool_call>") and '"name"' in message and '"arguments"' in message:
            return action_type("invalid", message="Tool call contains surrounding text or multiple calls")
        return super().parse_output(message)

    def clean_output(self, raw):
        message = super().clean_output(raw)
        # Some serving/tokenizer versions return the empty thinking prefix.
        # Never strip a nonempty reasoning block or speak it as a reply.
        return re.sub(r"\A<think>\s*</think>\s*", "", message)
