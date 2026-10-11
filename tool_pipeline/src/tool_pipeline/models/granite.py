"""Dynamic staged Granite routing using native function-call generation."""

import asyncio
import json
from pathlib import Path

from speech_contracts import RunSettings

from ..reference import reference_module
from ..telemetry import TraceRecorder
from ..tools import ToolRegistry


class GraniteCaller:
    def __init__(self, settings: RunSettings, registry: ToolRegistry, trace: TraceRecorder):
        self.trace = trace
        self.registry = registry
        self.settings = settings
        self.gpu_pairs = []
        with trace.span("initialization.granite"):
            try:
                import torch
                from transformers import AutoTokenizer, AutoModelForCausalLM
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise RuntimeError(
                    "Granite dependencies missing. Install tool-pipeline[models] on the GPU server."
                ) from exc
            self.torch = torch
            source = settings.granite_model
            if not Path(source).is_dir():
                with trace.span("granite.resolve_snapshot", revision=settings.granite_revision):
                    source = snapshot_download(
                        source,
                        revision=settings.granite_revision,
                        allow_patterns=["*.json", "*.jinja", "*.txt", "*.safetensors"],
                    )
            self.model_revision = Path(source).name
            with trace.span("granite.load_tokenizer"):
                self.tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
            with trace.span("granite.load_weights"):
                self.model = AutoModelForCausalLM.from_pretrained(source, local_files_only=True)
            with trace.span("granite.model_transfer", device=settings.granite_device):
                if settings.granite_device.startswith("cuda"):
                    self.model = self.model.to(device=settings.granite_device, dtype=torch.float16)
                else:
                    self.model = self.model.to(settings.granite_device)
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
        with self.trace.span("granite.prompt_format"):
            prompt = self.tokenizer.apply_chat_template(
                messages, tools=schemas, add_generation_prompt=True, tokenize=False
            )
        with self.trace.span("granite.tokenize"):
            tokens = self.tokenizer(prompt, add_special_tokens=False, return_tensors="pt")
        tokens = self._operation("granite.input_transfer", lambda: tokens.to(self.model.device))
        with self.torch.inference_mode():
            output = self._operation(
                "granite.argument_generation",
                lambda: self.model.generate(
                    **tokens,
                    do_sample=False,
                    max_new_tokens=128,
                    pad_token_id=self.tokenizer.eos_token_id,
                ),
            )
        with self.trace.span("granite.output_decode"):
            generated_tokens = output[0][tokens["input_ids"].shape[-1]:]
            return self.tokenizer.decode(generated_tokens, skip_special_tokens=False).strip()

    def _route_options(self):
        options = [
            ("A", "no action: ordinary conversation, thanks, or unfinished speech", "none"),
            ("B", "clarification needed: a tool request is missing a required detail", "clarify"),
        ]
        if len(self.registry.schemas) > 20:
            raise ValueError("The bounded router supports at most 20 tools")
        for i, schema in enumerate(self.registry.schemas):
            function = schema["function"]
            options.append((chr(67 + i), function["description"], function["name"]))
        return options

    def _score_routes(self, transcript, options):
        menu = "\n".join(f"{label}: {description}" for label, description, _ in options)
        with self.trace.span("granite.route_prompt"):
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Classify the latest user speech for a tool router. "
                        "Return only one label letter."
                    ),
                },
                {"role": "user", "content": f"Labels:\n{menu}\nLatest speech: {transcript}\nLabel:"},
            ]
            prompt = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )
        with self.trace.span("granite.route_tokenize"):
            prompt_ids = self.tokenizer(
                prompt, add_special_tokens=False, return_tensors="pt"
            )["input_ids"]
            choices = {
                label: self.tokenizer(label, add_special_tokens=False, return_tensors="pt")["input_ids"]
                for label, _, _ in options
            }
        prompt_ids = self._operation(
            "granite.route_transfer", lambda: prompt_ids.to(self.model.device)
        )
        choices = {k: v.to(self.model.device) for k, v in choices.items()}
        def score():
            torch = self.torch
            with torch.inference_mode():
                if all(v.shape[1] == 1 for v in choices.values()):
                    logits = self.model(input_ids=prompt_ids, use_cache=False).logits[:, -1, :]
                    scores = torch.log_softmax(logits, dim=-1)
                    return {k: float(scores[0, v[0, 0]].item()) for k, v in choices.items()}
                result = {}
                for label, ids in choices.items():
                    full = torch.cat((prompt_ids, ids), dim=1)
                    logits = self.model(input_ids=full, use_cache=False).logits
                    offset = prompt_ids.shape[1] - 1
                    probs = torch.log_softmax(logits[:, offset:offset + ids.shape[1], :], dim=-1)
                    result[label] = float(probs.gather(-1, ids.unsqueeze(-1)).mean().item())
                return result
        return self._operation("granite.route_scoring", score)

    def route(self, transcript):
        options = self._route_options()
        scores = self._score_routes(transcript, options)
        ordered = sorted(scores, key=scores.get, reverse=True)
        selected = next(action for label, _, action in options if label == ordered[0])
        routing = {
            "selected": ordered[0],
            "scores": scores,
            "margin": scores[ordered[0]] - scores[ordered[1]],
        }
        self.trace.event("caller.route", **routing)
        if selected in {"none", "clarify"}:
            return {"kind": selected, "routing": routing, "raw": json.dumps(routing)}
        schema = next(s for s in self.registry.schemas if s["function"]["name"] == selected)
        messages = [
            {
                "role": "system",
                "content": (
                    "Call the provided tool. Copy only details explicitly present in the user "
                    "speech. Output only the native tool call."
                ),
            },
            {"role": "user", "content": transcript},
        ]
        raw = self.generate(messages, [schema])
        with self.trace.span("granite.parse_output", raw=raw):
            action = reference_module("caller").parse_granite_output(raw)
            if action.kind != "call" or action.tool != selected:
                return {
                    "kind": "invalid", "raw": raw, "routing": routing,
                    "message": "Argument generation did not call the selected tool",
                }
            return {
                "kind": "call", "tool": selected, "arguments": dict(action.arguments),
                "raw": raw, "routing": routing,
            }

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
