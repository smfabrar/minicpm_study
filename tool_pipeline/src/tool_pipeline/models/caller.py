"""Shared local model execution for native tool-calling adapters."""

import asyncio
import hashlib
from pathlib import Path

from speech_contracts import RunSettings

from ..reference import reference_module
from ..telemetry import TraceRecorder
from ..tools import ToolRegistry


class NativeToolCaller:
    family = "granite"
    template_options = {}
    end_tokens = ("<|end_of_text|>", "<|end_of_turn|>")

    def __init__(self, settings: RunSettings, registry: ToolRegistry, trace: TraceRecorder):
        self.trace = trace
        self.registry = registry
        self.settings = settings
        self.gpu_pairs = []
        config = settings.caller
        with trace.span(f"initialization.{self.family}"):
            try:
                import torch
                from transformers import AutoTokenizer, AutoModelForCausalLM
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise RuntimeError(
                    "Caller dependencies missing. Install tool-pipeline[models] on the GPU server."
                ) from exc
            self.torch = torch
            source = config.model
            if not Path(source).is_dir():
                with trace.span(f"{self.family}.resolve_snapshot", revision=config.revision):
                    source = snapshot_download(
                        source,
                        revision=config.revision,
                        allow_patterns=["*.json", "*.jinja", "*.txt", "*.safetensors"],
                    )
            self.model_revision = Path(source).name
            with trace.span(f"{self.family}.load_tokenizer"):
                self.tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
            with trace.span(f"{self.family}.load_weights"):
                self.model = AutoModelForCausalLM.from_pretrained(source, local_files_only=True)
            with trace.span(f"{self.family}.model_transfer", device=config.device):
                if config.device.startswith("cuda"):
                    self.model = self.model.to(device=config.device, dtype=torch.float16)
                else:
                    self.model = self.model.to(config.device)
                self.model.eval()

    def _operation(self, name, operation):
        with self.trace.span(name) as span:
            if self.model.device.type == "cuda":
                with self.torch.cuda.device(self.model.device):
                    begin = self.torch.cuda.Event(enable_timing=True)
                    end = self.torch.cuda.Event(enable_timing=True)
                    begin.record()
                    result = operation()
                    end.record()
                    self.gpu_pairs.append((span, begin, end))
                    return result
            return operation()

    def generate(self, messages, schemas):
        with self.trace.span(f"{self.family}.prompt_format") as span:
            prompt = self.tokenizer.apply_chat_template(
                messages, tools=schemas, add_generation_prompt=True, tokenize=False,
                **self.template_options,
            )
            span.attributes.update(
                prompt=prompt,
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                tool_names=[schema["function"]["name"] for schema in schemas],
                **self.template_options,
            )
        with self.trace.span(f"{self.family}.tokenize"):
            tokens = self.tokenizer(prompt, add_special_tokens=False, return_tensors="pt")
        tokens = self._operation(f"{self.family}.input_transfer", lambda: tokens.to(self.model.device))
        with self.torch.inference_mode():
            output = self._operation(
                f"{self.family}.native_generation",
                lambda: self.model.generate(
                    **tokens,
                    do_sample=False,
                    max_new_tokens=128,
                    pad_token_id=self.tokenizer.eos_token_id,
                ),
            )
        with self.trace.span(f"{self.family}.output_decode"):
            generated_tokens = output[0][tokens["input_ids"].shape[-1]:]
            return self.tokenizer.decode(generated_tokens, skip_special_tokens=False).strip()

    def route(self, transcript):
        messages = [
            {
                "role": "system",
                "content": (
                    "Use an appropriate provided tool when the user requests a lookup, search, "
                    "calculation, or another operation covered by a tool. "
                    "Copy only argument details explicitly present in the user speech. "
                    "Omit optional arguments that were not provided. "
                    "For a tool with no parameters, use an empty arguments object. "
                    "Return at most one native tool call, without surrounding prose. "
                    "If a required detail is missing, ask a concise clarification question "
                    "in plain text instead of inventing an argument. "
                    "For ordinary conversation, respond concisely in plain text."
                ),
            },
            {"role": "user", "content": transcript},
        ]
        raw = self.generate(messages, self.registry.schemas)
        with self.trace.span(f"{self.family}.parse_output", raw=raw):
            message = self.clean_output(raw)
            action = reference_module("caller").parse_granite_output(message)
            if action.kind == "call":
                if action.tool not in self.registry.definitions:
                    return {"kind": "invalid", "raw": raw, "message": "Tool is not allowlisted"}
                return {
                    "kind": "call", "tool": action.tool, "arguments": dict(action.arguments),
                    "raw": raw,
                }
            plain_reply = action.kind == "invalid" and action.message in {
                "unstructured caller output", "unknown caller action",
            }
            control_markers = (
                "<|", "<tool_call", "</tool_call", "<think>", "</think>",
                "<function=", "<parameter=",
            )
            if (message and plain_reply and not message.startswith(("{", "["))
                    and not any(marker in message for marker in control_markers)):
                return {"kind": "respond", "message": message, "raw": raw}
            return {"kind": "invalid", "raw": raw,
                    "message": action.message or "Expected a native tool call or plain assistant response"}

    def clean_output(self, raw):
        message = raw.strip()
        for suffix in self.end_tokens:
            if message.endswith(suffix):
                message = message.removesuffix(suffix).strip()
        return message

    async def decide(self, transcript):
        with self.trace.span("caller.total"):
            return await asyncio.to_thread(self.route, transcript)

    def finalize_gpu_metrics(self):
        if not self.gpu_pairs:
            return {}
        self.torch.cuda.synchronize(self.model.device)
        for span, begin, end in self.gpu_pairs:
            span.attributes["gpu_elapsed_ms"] = begin.elapsed_time(end)
            span.attributes["gpu_timing_kind"] = (
                "CUDA stream elapsed time; may include idle time and contention"
            )
        device = self.model.device
        return {
            "device": str(device),
            "allocated_bytes": self.torch.cuda.memory_allocated(device),
            "reserved_bytes": self.torch.cuda.memory_reserved(device),
            "peak_allocated_bytes": self.torch.cuda.max_memory_allocated(device),
            "peak_reserved_bytes": self.torch.cuda.max_memory_reserved(device),
        }
