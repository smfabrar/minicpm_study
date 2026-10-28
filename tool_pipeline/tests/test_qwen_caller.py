"""Qwen protocol fixtures; model quality and GPU performance need real runs."""

import asyncio
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fixtures import default_tools
from speech_contracts import RunSettings
from tool_pipeline.models.factory import create_caller
from tool_pipeline.models.qwen import QwenCaller
from tool_pipeline.telemetry import TraceRecorder
from tool_pipeline.tools import ToolRegistry


def caller_with_output(raw):
    caller = QwenCaller.__new__(QwenCaller)
    caller.registry = ToolRegistry(default_tools(), TraceRecorder())
    caller.trace = TraceRecorder()
    caller.generate = Mock(return_value=raw)
    return caller


@pytest.mark.parametrize('prefix', ['', '<think>\n\n</think>\n\n'])
def test_qwen_native_call_executes_with_existing_tools(prefix):
    raw = prefix + '<tool_call>\n{"name":"calculator","arguments":{"expression":"24 * 4"}}\n</tool_call><|im_end|>'
    caller = caller_with_output(raw)
    action = asyncio.run(caller.decide('What is 24 times 4?'))
    assert action == {'kind': 'call', 'tool': 'calculator', 'arguments': {'expression': '24 * 4'}, 'raw': raw}
    result = asyncio.run(caller.registry.execute(action['tool'], action['arguments'], 'What is 24 times 4?'))
    assert result['facts'] == '24 * 4 = 96.'


@pytest.mark.parametrize('reply', ['Hello!', 'Which seminar do you mean?'])
def test_qwen_plain_response_strips_end_token(reply):
    action = caller_with_output(reply + '<|im_end|>').route('Hello')
    assert action['kind'] == 'respond'
    assert action['message'] == reply


def test_qwen_calls_an_authored_zero_argument_python_tool(tmp_path):
    definition = {
        'name': 'read_status', 'description': 'Read the experiment status',
        'kind': 'python', 'parameter': 'query',
        'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
        'python_code': 'def execute(arguments):\n    return "Experiment ready"\n',
    }
    caller = caller_with_output('<tool_call>{"name":"read_status","arguments":{}}</tool_call><|im_end|>')
    caller.registry = ToolRegistry([definition], caller.trace, tmp_path)
    action = caller.route('Read the experiment status')
    assert action['kind'] == 'call'
    result = asyncio.run(caller.registry.execute(action['tool'], action['arguments'], 'Read the experiment status'))
    assert result['facts'] == 'Experiment ready'
    assert (tmp_path / result['execution_file']).is_file()


@pytest.mark.parametrize('raw', [
    '<|im_end|>',
    '<tool_call>{"name":"calculator","arguments":',
    '<tool_call>{"name":"calculator","arguments":[]}</tool_call><|im_end|>',
    '<tool_call>{"name":"unknown_tool","arguments":{}}</tool_call><|im_end|>',
    '<tool_call>{"name":"calculator","arguments":{}}</tool_call> Extra prose.<|im_end|>',
    '<tool_call>{"name":"calculator","arguments":{}}</tool_call>'
    '<tool_call>{"name":"document_search","arguments":{}}</tool_call><|im_end|>',
    '<think>I should call a tool</think>Hello!<|im_end|>',
    'Reasoning text</think>Hello!<|im_end|>',
    '<tool_call><function=calculator></function></tool_call><|im_end|>',
])
def test_qwen_invalid_outputs_cannot_be_spoken_or_executed(raw):
    action = caller_with_output(raw).route('Hello')
    assert action['kind'] == 'invalid'
    assert action['raw'] == raw


def test_generation_disables_thinking_and_retains_prompt_telemetry():
    caller = QwenCaller.__new__(QwenCaller)
    caller.trace = TraceRecorder()
    caller.gpu_pairs = []
    caller.torch = SimpleNamespace(inference_mode=nullcontext)
    caller.model = SimpleNamespace(device=SimpleNamespace(type='cpu'))
    tokens = SimpleNamespace(shape=(1, 3))

    class Batch(dict):
        def to(self, device):
            return self

    class Tokenizer:
        eos_token_id = 151645

        def apply_chat_template(self, messages, **kwargs):
            assert kwargs['enable_thinking'] is False
            assert kwargs['tools'][0]['function']['name'] == 'calculator'
            assert kwargs['add_generation_prompt'] is True
            assert kwargs['tokenize'] is False
            return 'prompt with tools and an empty thinking block'

        def __call__(self, prompt, **kwargs):
            assert kwargs == {'add_special_tokens': False, 'return_tensors': 'pt'}
            return Batch(input_ids=tokens)

        def decode(self, generated, **kwargs):
            assert generated == [4, 5]
            assert kwargs == {'skip_special_tokens': False}
            return 'Hello!<|im_end|>'

    def generate(**kwargs):
        assert kwargs['do_sample'] is False
        assert kwargs['max_new_tokens'] == 128
        assert kwargs['pad_token_id'] == 151645
        return [[1, 2, 3, 4, 5]]

    caller.model.generate = generate
    caller.tokenizer = Tokenizer()
    assert caller.generate([{'role': 'user', 'content': 'Hello'}], [
        {'type': 'function', 'function': {'name': 'calculator'}}
    ]) == 'Hello!<|im_end|>'
    spans = caller.trace.snapshot()['spans']
    prompt = next(span for span in spans if span['name'] == 'qwen3.prompt_format')
    assert prompt['attributes']['enable_thinking'] is False
    assert len(prompt['attributes']['prompt_sha256']) == 64
    assert any(span['name'] == 'qwen3.native_generation' for span in spans)


def test_factory_selects_qwen_without_loading_granite(monkeypatch):
    def initialized(self, settings, registry, trace):
        self.settings = settings
    monkeypatch.setattr(QwenCaller, '__init__', initialized)
    caller = create_caller(RunSettings(caller_backend='qwen3', caller_device='cuda:0'), None, None)
    assert isinstance(caller, QwenCaller)
    assert caller.settings.caller.model == 'Qwen/Qwen3-1.7B'


@pytest.mark.parametrize('backend, expected_model', [
    ('granite', '/saved/granite'), ('qwen3', 'Qwen/Qwen3-1.7B'),
])
def test_loading_resolves_selected_model_revision_and_device(monkeypatch, backend, expected_model):
    loaded = []

    class Model:
        dtype = 'torch.float16'
        device = 'cuda:0'

        def get_memory_footprint(self):
            return 3400000000

        def to(self, **kwargs):
            self.transfer = kwargs
            return self

        def eval(self):
            pass

    def snapshot(model, **kwargs):
        loaded.append((model, kwargs['revision']))
        return '/cache/snapshots/pinned-commit'

    def load(source, **kwargs):
        assert source == '/cache/snapshots/pinned-commit'
        assert kwargs == {'local_files_only': True}
        return Model()

    loader = SimpleNamespace(from_pretrained=load)
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(float16='float16'))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(AutoTokenizer=loader, AutoModelForCausalLM=loader))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(snapshot_download=snapshot))
    settings = RunSettings(caller_backend=backend, granite_model='/saved/granite', granite_revision='granite-sha', caller_device='cuda:0')
    caller = create_caller(settings, None, TraceRecorder())
    assert loaded == [(expected_model, 'main' if backend == 'qwen3' else 'granite-sha')]
    assert caller.model_revision == 'pinned-commit'
    assert caller.model.transfer == {'device': 'cuda:0', 'dtype': 'float16'}
