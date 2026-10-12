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
