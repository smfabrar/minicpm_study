"""Qwen3 tool calls using its native template with thinking disabled."""

import re

from .caller import NativeToolCaller


class QwenCaller(NativeToolCaller):
    family = "qwen3"
    template_options = {"enable_thinking": False}
    end_tokens = ("<|im_end|>", "<|endoftext|>")

    def clean_output(self, raw):
        message = super().clean_output(raw)
        # Some serving/tokenizer versions return the empty thinking prefix.
        # Never strip a nonempty reasoning block or speak it as a reply.
        return re.sub(r"\A<think>\s*</think>\s*", "", message)
