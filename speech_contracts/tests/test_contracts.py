"""Only serialized request and schema behavior belongs to this package."""
import tomllib
from pathlib import Path

import pytest
from speech_contracts import RunRequest, RunSettings, SynthesisRequest, function_schema


def test_b1_serialization_has_no_oracle_and_preserves_settings():
    request = RunRequest('B1', '/input.wav', settings=RunSettings(granite_device='cuda:0'))
    payload = request.to_payload()
    assert 'oracle_result' not in payload
    assert RunRequest.from_dict(payload).settings.granite_device == 'cuda:0'
    with pytest.raises(ValueError, match='oracle'):
        RunRequest.from_dict({**payload, 'oracle_result': 'hidden fact'})


def test_synthesis_identity_changes_with_question_or_voice():
    request = SynthesisRequest('Hello')
    assert request.cache_key() == SynthesisRequest('Hello').cache_key()
    assert request.cache_key() != SynthesisRequest('Goodbye').cache_key()
    assert request.cache_key() != SynthesisRequest('Hello', RunSettings(voice='af_bella')).cache_key()
    assert request.to_payload()['job_kind'] == 'synthesis'


def test_function_schema_contains_one_required_string_argument():
    schema = function_schema({'name': 'lookup', 'description': 'Look up a fixture', 'parameter': 'query', 'kind': 'fixture'})
    parameters = schema['function']['parameters']
    assert parameters['required'] == ['query']
    assert parameters['properties']['query']['type'] == 'string'
    assert parameters['additionalProperties'] is False


@pytest.mark.parametrize('device', ['cpu', 'cuda', 'cuda:0', 'cuda:1'])
def test_tts_device_survives_serialization(device):
    request = SynthesisRequest('Hello', RunSettings(tts_device=device))
    assert RunSettings.from_dict(request.to_payload()['settings']).tts_device == device


@pytest.mark.parametrize('device', ['auto', 'mps', 'cuda:-1', 'cuda:', 'cuda:0x', '', None])
def test_tts_device_rejects_invalid_values(device):
    with pytest.raises(ValueError, match='[Tt][Tt][Ss]|tts_device'):
        RunSettings(tts_device=device)


def test_gpu_synthesis_does_not_reuse_cpu_cache():
    cpu = SynthesisRequest('Hello')
    gpu = SynthesisRequest('Hello', RunSettings(tts_device='cuda:0'))
    assert cpu.settings.tts_device == 'cpu'
    assert cpu.cache_key() != gpu.cache_key()
    assert gpu.cache_key() != SynthesisRequest('Hello', RunSettings(tts_device='cuda:1')).cache_key()


def test_contract_distribution_has_no_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    assert project['dependencies'] == []
    assert 'scripts' not in project


def test_legacy_study_resolves_original_granite_configuration():
    settings = RunSettings.from_dict({'granite_model': '/models/granite', 'granite_revision': 'saved-sha', 'granite_device': 'cuda:0'})
    assert settings.caller.backend == 'granite'
    assert settings.caller.model == '/models/granite'
    assert settings.caller.revision == 'saved-sha'
    assert settings.caller.device == 'cuda:0'


def test_qwen_selection_roundtrips_without_reusing_granite_snapshot():
    settings = RunSettings(caller_backend='qwen3', granite_model='/models/granite', granite_revision='granite-sha', granite_device='cuda:0')
    request = RunRequest('B1', '/input.wav', settings=settings)
    restored = RunRequest.from_dict(request.to_payload()).settings
    assert restored.caller.model == 'Qwen/Qwen3-1.7B'
    assert restored.caller.revision == 'main'
    assert restored.caller.device == 'cuda:0'
    explicit = RunSettings(caller_backend='qwen3', caller_model='/models/qwen', caller_revision='qwen-sha', caller_device='cpu')
    assert explicit.caller.model == '/models/qwen'
    assert explicit.caller.revision == 'qwen-sha'
    assert explicit.caller.device == 'cpu'


@pytest.mark.parametrize('changes', [{'caller_backend': 'unknown'}, {'caller_device': 'cuda:-1'}, {'caller_model': '  '}, {'caller_revision': '  '}])
def test_invalid_caller_configuration_fails_before_inference(changes):
    with pytest.raises(ValueError, match='Caller'):
        RunSettings(**changes)


def test_nf4_is_saved_in_requests_without_changing_prepared_audio_identity():
    settings = RunSettings(caller_backend='qwen3', caller_device='cuda:0', caller_quantization='nf4')
    request = RunRequest('B1', '/input.wav', settings=settings)
    restored = RunRequest.from_dict(request.to_payload()).settings
    assert restored.caller.quantization == 'nf4'
    assert RunSettings.from_dict({}).caller.quantization == 'none'
    assert SynthesisRequest('Hello', settings).cache_key() == SynthesisRequest('Hello').cache_key()


@pytest.mark.parametrize('changes', [
    {'caller_quantization': 'int8'},
    {'caller_backend': 'qwen3', 'caller_device': 'cpu', 'caller_quantization': 'nf4'},
    {'caller_backend': 'granite', 'caller_device': 'cuda:0', 'caller_quantization': 'nf4'},
])
def test_unsupported_quantization_is_rejected_before_job_submission(changes):
    with pytest.raises(ValueError, match='quantization'):
        RunSettings(**changes)
