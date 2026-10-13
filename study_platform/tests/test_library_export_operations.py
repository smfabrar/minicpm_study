"""CPU checks for study lifecycle, reproducible tools, archives and queue evidence."""

import hashlib
import io
import json
import threading
import zipfile
from dataclasses import asdict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from speech_study.app import create_app
from speech_study.domain.models import RunStatus
from speech_study.infrastructure.background import BackgroundQueue
from speech_study.infrastructure.unit_of_work import UnitOfWork
from test_studies import recording


@pytest.fixture
def platform(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    services = app.state.services
    study = client.post('/api/studies', json={'name': 'Time experiment'}).json()
    yield client, services, '/api/studies/' + study['id']
    services.operations.close()


def clock_tool():
    return {'name': 'current_datetime', 'description': 'Get current UTC time', 'kind': 'python',
            'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
            'python_code': 'def execute(arguments):\n    return "Clock fixture"\n'}


def prepared_case(client, base):
    case = client.post(base + '/cases', json={'question': 'What time is it?', 'split': 'evaluation',
                       'category': 'custom', 'oracle_result': 'Clock fixture'}).json()
    return client.post(f"{base}/cases/{case['id']}/audio", files={'audio': ('input.wav', recording(), 'audio/wav')}).json()


def test_library_copies_are_independent_and_freeze_preserves_source(platform):
    client, services, base = platform
    response = client.post('/api/tools', json=clock_tool())
    assert response.status_code == 201, response.text
    library = response.json()
    attached = client.post(base + '/tools/attach', json={'library_id': library['id']})
    assert attached.status_code == 201, attached.text
    another = client.post('/api/studies', json={'name': 'Another study'}).json()
    copy = client.post(f"/api/studies/{another['id']}/tools/attach", json={'library_id': library['id']}).json()
    assert copy['id'] != attached.json()['id']
    assert client.post(base + '/tools/attach', json={'library_id': library['id']}).status_code == 409
    changed = {**clock_tool(), 'python_code': 'def execute(arguments):\n    return "Changed"\n'}
    assert client.put('/api/tools/' + library['id'], json=changed).status_code == 200
    assert client.get(base).json()['tools'][-1]['python_code'] == clock_tool()['python_code']
    prepared_case(client, base)
    frozen = client.post(base + '/freeze').json()
    assert frozen['snapshot']['tools'][-1]['python_code'] == clock_tool()['python_code']
    assert client.post(base + '/tools/attach', json={'library_id': library['id']}).status_code == 409
    assert client.delete('/api/tools/' + library['id']).status_code == 204
    assert client.get(base).json()['tools'][-1]['python_code'] == clock_tool()['python_code']


def test_library_validation_and_persistence(platform, tmp_path):
    client, _, base = platform
    assert client.post('/api/tools', json={**clock_tool(), 'python_code': 'bad !!!'}).status_code == 400
    assert client.post('/api/tools', json={**clock_tool(), 'parameters': {'type': 'array'}}).status_code == 400
    saved = client.post('/api/tools', json=clock_tool()).json()
    restarted = TestClient(create_app(tmp_path))
    assert restarted.get('/api/tools').json()[0]['id'] == saved['id']
    assert restarted.get(base).status_code == 200


def test_trash_keeps_shared_recordings_and_can_restore_after_restart(platform, tmp_path):
    client, services, base = platform
    case = prepared_case(client, base)
    clone = client.post(base + '/clone').json()
    assert client.delete(base).status_code == 204
    assert client.get(base).status_code == 404
    assert [s['id'] for s in client.get('/api/studies').json()] == [clone['id']]
    assert client.get('/api/studies?deleted=true').json()[0]['id'] == base.rsplit('/', 1)[1]
    assert services.artifacts.resolve(case['audio_path']).is_file()
    restarted = TestClient(create_app(tmp_path))
    assert restarted.post(base + '/restore').status_code == 200
    assert restarted.get(base).json()['cases'][0]['audio_sha256'] == case['audio_sha256']


@pytest.mark.parametrize('kind', ['synthesis', 'transcription'])
def test_active_study_operations_block_deletion(platform, kind):
    client, services, base = platform
    services.operations.submit(kind, {'study_id': base.rsplit('/', 1)[1]})
    assert client.delete(base).status_code == 409


def test_queued_run_blocks_deletion_and_frozen_request_contains_python(platform):
    client, services, base = platform
    client.post(base + '/tools', json=clock_tool())
    case = prepared_case(client, base)
    client.post(base + '/freeze')
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}):
        response = client.post(base + '/runs', json={'case_id': case['id'], 'conditions': ['B1']})
    assert response.status_code == 202, response.text
    assert response.json()[0]['request']['tools'][-1]['parameters']['required'] == []
    assert client.delete(base).status_code == 409


def test_export_includes_historical_audio_python_source_logs_and_checksums(platform):
    client, services, base = platform
    client.post(base + '/tools', json=clock_tool())
    case = prepared_case(client, base)
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}):
        run = client.post(base + '/runs', json={'case_id': case['id'], 'conditions': ['B1']}).json()[0]
    services.artifacts.write(f"runs/{run['id']}/worker.log", b'worker evidence')
    services.artifacts.write(f"runs/{run['id']}/tool-clock-execution.json", b'{"facts": "time"}')
    client.put(base + '/cases/' + case['id'], json={'question': 'A new question'})
    assert client.get(base).json()['cases'][0]['audio_path'] is None
    response = client.get(base + '/export')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {'study.json', 'settings.json', 'tools.json', 'analysis.json', 'runs.csv', 'manifest.json', 'operations.json', case['audio_path']} <= names
        assert f"runs/{run['id']}/worker.log" in names
        assert any(name.startswith('tool_sources/') and name.endswith('.py') for name in names)
        assert any(name.startswith('operations/') and name.endswith('.log') for name in names)
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['pending_runs'] == [run['id']]
        assert len(manifest['files']) == len(names) - 1
        for file in manifest['files']:
            content = archive.read(file['path'])
            assert len(content) == file['size_bytes']
            assert hashlib.sha256(content).hexdigest() == file['sha256']


def test_missing_artifacts_are_reported(platform):
    client, services, base = platform
    case = prepared_case(client, base)
    services.artifacts.resolve(case['audio_path']).unlink()
    with zipfile.ZipFile(io.BytesIO(client.get(base + '/export').content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert case['audio_path'] in manifest['missing_artifacts']


def test_queue_shows_all_active_operations_and_positions(tmp_path):
    queue = BackgroundQueue(tmp_path / 'operations')
    queue.register('example', lambda payload: None)
    operations = [queue.submit('example', {'number': number}) for number in range(105)]
    listed = queue.list()
    assert len(listed) == 105
    assert {o.queue_position for o in listed} == set(range(1, 106))
    assert next(o.queue_position for o in listed if o.id == operations[0].id) == 1
    assert next(o.queue_position for o in listed if o.id == operations[-1].id) == 105


def test_operation_details_persist_progress_payload_and_traceback(platform):
    client, services, base = platform
    completed = threading.Event()
    def fail(payload):
        services.operations.report('Reading files', details={'directory': '/workspace/documents'})
        completed.set()
        raise LookupError('document missing')
    services.operations.register('example', fail)
    operation = services.operations.submit('example', {'study_id': base.rsplit('/', 1)[1]})
    services.operations.start()
    assert completed.wait(3)
    services.operations.queue.join()
    details = client.get('/api/operations/' + operation.id).json()
    assert details['status'] == 'failed'
    assert details['started_at'] and details['finished_at']
    assert details['payload']['study_id'] == base.rsplit('/', 1)[1]
    assert 'Reading files' in details['log'] and 'Traceback' in details['log'] and 'document missing' in details['log']
    assert client.get('/api/operations/bad-id').status_code == 404


def test_operation_detail_uses_local_runtime_logs_when_server_is_offline(platform):
    client, services, base = platform
    operation = services.operations.submit('synthesis', {'study_id': base.rsplit('/', 1)[1]})
    operation.status = 'complete'
    operation.remote_job_id = 'a' * 32
    operation.runtime_url = 'http://127.0.0.1:1'
    operation.artifact_directory = 'audio/test'
    services.operations._save(operation)
    services.artifacts.write('audio/test/worker.log', b'local preserved log')
    assert client.get('/api/operations/' + operation.id).json()['runtime_logs']['worker.log'] == 'local preserved log'


def test_export_reports_missing_generated_recording_and_declared_tool_evidence(platform):
    client, services, base = platform
    case = prepared_case(client, base)
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}):
        run = client.post(base + '/runs', json={'case_id': case['id'], 'conditions': ['B0']}).json()[0]
    with UnitOfWork(services.runs.database) as work:
        saved = work.runs.get(run['id'])
        saved.status = RunStatus.COMPLETE
        saved.result = {'output_audio': 'output.wav'}
        work.runs.save(saved)
    services.artifacts.write_json(f"runs/{run['id']}/remote_job.json", {'artifacts': ['output.wav', 'tool-clock-execution.json']})
    services.artifacts.write(f"runs/{run['id']}/telemetry.json", b'{}')
    services.artifacts.write(f"runs/{run['id']}/reference.wav", recording())
    with zipfile.ZipFile(io.BytesIO(client.get(base + '/export').content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert f"runs/{run['id']}/output.wav" in manifest['missing_artifacts']
        assert f"runs/{run['id']}/tool-clock-execution.json" in manifest['missing_artifacts']


def test_case_expectations_preserve_arbitrary_json_arguments(platform):
    client, _, base = platform
    arguments = {'count': 3, 'enabled': True, 'items': ['a', 'b'], 'options': {'limit': 2}}
    response = client.post(base + '/cases', json={'question': 'Use my custom function', 'expected_arguments': arguments})
    assert response.status_code == 201, response.text
    assert response.json()['expected_arguments'] == arguments
    assert client.get(base).json()['cases'][0]['expected_arguments'] == arguments
