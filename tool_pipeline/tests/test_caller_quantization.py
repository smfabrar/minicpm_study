"""Exercise the loading boundary without claiming real GPU memory savings."""

import sys
from types import SimpleNamespace

import pytest

from speech_contracts import RunSettings
from tool_pipeline.models.factory import create_caller
from tool_pipeline.telemetry import TraceRecorder


@pytest.fixture
def quantized_loader(monkeypatch):
    calls = []
    model = SimpleNamespace(
        is_loaded_in_4bit=True, dtype='torch.float16', device='cuda:0',
        eval=lambda: None, get_memory_footprint=lambda: 1350000000,
    )

    def forbidden_transfer(*args, **kwargs):
        raise AssertionError('Quantized models must load directly on the device, without .to()')

    model.to = forbidden_transfer

    def load(source, **kwargs):
        calls.append((source, kwargs))
        return model

    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(float16='torch.float16'))
    monkeypatch.setitem(sys.modules, 'bitsandbytes', SimpleNamespace(__version__='0.48.2'))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        AutoTokenizer=SimpleNamespace(from_pretrained=lambda *args, **kwargs: object()),
        AutoModelForCausalLM=SimpleNamespace(from_pretrained=load),
        BitsAndBytesConfig=lambda **kwargs: SimpleNamespace(**kwargs),
    ))
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        snapshot_download=lambda *args, **kwargs: '/cache/snapshots/qwen-commit',
    ))
    return calls, model


def nf4_settings():
    return RunSettings(caller_backend='qwen3', caller_device='cuda:0', caller_quantization='nf4')


def test_nf4_loads_once_on_selected_device_and_records_actual_configuration(quantized_loader):
    calls, model = quantized_loader
    trace = TraceRecorder()
    caller = create_caller(nf4_settings(), None, trace)
    assert caller.model is model
    assert len(calls) == 1
    source, options = calls[0]
    assert source == '/cache/snapshots/qwen-commit'
    assert options['local_files_only'] is True
    assert options['device_map'] == {'': 'cuda:0'}
    assert options['torch_dtype'] == 'torch.float16'
    assert options['low_cpu_mem_usage'] is True
    config = options['quantization_config']
    assert config.load_in_4bit is True
    assert config.bnb_4bit_quant_type == 'nf4'
    assert config.bnb_4bit_use_double_quant is True
    assert config.bnb_4bit_compute_dtype == 'torch.float16'
    assert caller.loading_provenance == {
        'quantization': 'nf4', 'weight_format': 'nf4', 'compute_dtype': 'float16',
        'double_quantization': True, 'device': 'cuda:0', 'bitsandbytes_version': '0.48.2',
        'model_memory_footprint_bytes': 1350000000,
    }
    snapshot = trace.snapshot()
    assert any(event['name'] == 'caller.loaded' for event in snapshot['events'])
    loading = next(span for span in snapshot['spans'] if span['name'] == 'qwen3.load_weights')
    assert loading['attributes']['includes_device_dispatch'] is True
    assert loading['attributes']['quantization'] == 'nf4'


def test_missing_bitsandbytes_does_not_fall_back_to_fp16(quantized_loader, monkeypatch):
    calls, _ = quantized_loader
    monkeypatch.setitem(sys.modules, 'bitsandbytes', None)
    with pytest.raises(RuntimeError, match='NF4 requires bitsandbytes'):
        create_caller(nf4_settings(), None, TraceRecorder())
    assert calls == []


def test_ignored_quantization_is_an_error_instead_of_mislabelled_results(quantized_loader):
    calls, model = quantized_loader
    model.is_loaded_in_4bit = False
    with pytest.raises(RuntimeError, match='not loaded in 4-bit'):
        create_caller(nf4_settings(), None, TraceRecorder())
    assert len(calls) == 1


def test_quantized_allocation_failure_does_not_trigger_another_load(quantized_loader, monkeypatch):
    attempts = []

    def out_of_memory(*args, **kwargs):
        attempts.append(kwargs)
        raise RuntimeError('CUDA out of memory')

    monkeypatch.setattr(sys.modules['transformers'].AutoModelForCausalLM, 'from_pretrained', out_of_memory)
    with pytest.raises(RuntimeError, match='CUDA out of memory'):
        create_caller(nf4_settings(), None, TraceRecorder())
    assert len(attempts) == 1
