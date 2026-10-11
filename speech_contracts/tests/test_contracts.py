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


def test_contract_distribution_has_no_runtime_dependencies():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    assert project['dependencies'] == []
    assert 'scripts' not in project
