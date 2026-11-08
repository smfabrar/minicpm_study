"""Audio bundle deletion through the API with local and GridFS storage adapters."""

import importlib
import sys
import types
from pathlib import PurePosixPath
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from speech_study.app import create_app
from speech_study.domain.models import RunStatus
from speech_study.infrastructure.unit_of_work import UnitOfWork
from test_cloud_storage import Bucket, FakeDB
from test_studies import recording


@pytest.fixture(params=['local', 'gridfs'])
def platform(tmp_path, request, monkeypatch):
    app = create_app(tmp_path)
    services = app.state.services
    cloud = None
    if request.param == 'gridfs':
        monkeypatch.setitem(sys.modules, 'gridfs', types.SimpleNamespace(GridFSBucket=Bucket))
        monkeypatch.setitem(sys.modules, 'gridfs.errors', types.SimpleNamespace(NoFile=FileNotFoundError))
        sys.modules.pop('speech_study.infrastructure.gridfs_store', None)
        module = importlib.import_module('speech_study.infrastructure.gridfs_store')
        cloud = FakeDB()
        store = module.GridFSArtifactStore(services.artifacts.root, cloud)
        services.artifacts = store
        for service in (services.studies, services.preparation, services.runs, services.exports,
                        services.analysis, services.operation_details):
            service.artifacts = store
        services.operations.store = module.GridFSArtifactStore(tmp_path / 'operations', cloud, 'operations')
    client = TestClient(app)
    study = client.post('/api/studies', json={'name': 'Voice collection'}).json()
    base = '/api/studies/' + study['id']
    case = client.post(base + '/cases', json={'question': 'Hello there', 'split': 'evaluation'}).json()
    yield client, services, base, case, cloud
    services.operations.close()
    if cloud is not None:
        sys.modules.pop('speech_study.infrastructure.gridfs_store', None)


def attach(client, base, case, origin='uploaded'):
    response = client.post(f"{base}/cases/{case['id']}/audio?origin={origin}",
                           files={'audio': ('voice.wav', recording(), 'audio/wav')})
    assert response.status_code == 200, response.text
    return response.json()


def test_recorded_and_uploaded_bundles_are_completely_removed(platform):
    client, services, base, case, cloud = platform
    for origin in ('recorded', 'uploaded'):
        case = attach(client, base, case, origin)
        directory = str(PurePosixPath(case['audio_path']).parent)
        assert services.artifacts.resolve(directory + '/original.wav').is_file()
        response = client.delete(f"{base}/cases/{case['id']}/audio")
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved['question'] == 'Hello there'
        assert saved['audio_path'] is saved['audio_sha256'] is saved['audio_origin'] is None
        assert saved['preparation_trace'] is None and saved['audio_provenance'] == {}
        assert not saved['audio_deletion_pending']
        assert not services.artifacts.resolve(directory).exists()
        assert directory not in client.get(base).json()['artifact_directories']
        if cloud is not None:
            assert not cloud['artifacts_paths'].rows
            assert not cloud['artifacts_fixture']
        assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 200


def test_tts_deletion_removes_preparation_results_traces_and_operation_logs(platform):
    client, services, base, case, cloud = platform
    files = {'original.wav': recording(), 'input.wav': recording(), 'telemetry.json': b'{}',
             'result.json': b'{}', 'worker.log': b'TTS preparation log'}
    job = {'id': 'a' * 32, 'status': 'complete', 'artifacts': list(files),
           'result': {'provenance': {'model': 'CPU test fixture'}}}
    runtime = Mock()
    runtime.submit.return_value = job
    runtime.artifact.side_effect = lambda job_id, name: files[name]
    payload = {'study_id': base.rsplit('/', 1)[1], 'case_id': case['id'],
               'question': case['question'], 'settings': client.get(base).json()['settings']}
    with patch('speech_study.services.preparation.RuntimeClient', return_value=runtime):
        services.preparation._synthesize(payload)
    case = client.get(base).json()['cases'][0]
    directory = str(PurePosixPath(case['audio_path']).parent)
    assert case['audio_origin'] == 'synthesized'
    operation = services.operations.submit('synthesis', payload)
    operation.status, operation.artifact_directory = 'complete', directory
    services.operations._save(operation)
    assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 200
    assert not services.artifacts.resolve(directory).exists()
    assert services.operations.list(limit=None) == []
    if cloud is not None:
        for namespace in ('artifacts', 'operations'):
            assert not cloud[namespace + '_paths'].rows
            assert not cloud[namespace + '_fixture']


def test_shared_audio_is_reclaimed_when_last_case_detaches(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    clone = client.post(base + '/clone').json()
    clone_base = '/api/studies/' + clone['id']
    clone_case = client.get(clone_base).json()['cases'][0]
    assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 200
    assert services.artifacts.resolve(case['audio_path']).is_file()
    assert client.delete(f"{clone_base}/cases/{clone_case['id']}/audio").status_code == 200
    assert not services.artifacts.resolve(case['audio_path']).exists()


def test_deleting_question_also_deletes_its_audio_bundle(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    assert client.delete(f"{base}/cases/{case['id']}").status_code == 204
    assert client.get(base).json()['cases'] == []
    assert not services.artifacts.resolve(case['audio_path']).exists()
    if cloud is not None:
        assert not cloud['artifacts_paths'].rows
        assert not cloud['artifacts_fixture']


def test_active_work_frozen_studies_run_history_and_foreign_cases_are_protected(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    other = client.post('/api/studies', json={'name': 'Other'}).json()
    assert client.delete(f"/api/studies/{other['id']}/cases/{case['id']}/audio").status_code == 404
    operation = services.operations.submit('synthesis', {'study_id': case['study_id'], 'case_id': case['id']})
    assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 409
    operation.status = 'complete'
    services.operations._save(operation)
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}):
        response = client.post(base + '/runs', json={'case_id': case['id'], 'conditions': ['B0']})
    assert response.status_code == 202
    assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 409
    assert client.post(base + '/freeze').status_code == 200
    assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 409
    assert services.artifacts.resolve(case['audio_path']).is_file()


def test_partial_cleanup_can_be_retried_without_losing_its_path(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    directory = str(PurePosixPath(case['audio_path']).parent)
    original_delete = services.artifacts.delete

    def partial_failure(path):
        original_delete(directory + '/original.wav')
        raise OSError('Temporary storage failure')

    with patch.object(services.artifacts, 'delete', side_effect=partial_failure):
        with pytest.raises(OSError):
            client.delete(f"{base}/cases/{case['id']}/audio")
    saved = client.get(base).json()['cases'][0]
    assert saved['audio_deletion_pending'] and saved['audio_path'] == case['audio_path']
    assert client.put(f"{base}/cases/{case['id']}", json={'question': 'Change'}).status_code == 409
    assert client.delete(f"{base}/cases/{case['id']}").status_code == 409
    assert client.post(base + '/freeze').status_code == 409
    assert client.post(base + '/clone').status_code == 409
    response = client.post(f"{base}/cases/{case['id']}/audio", files={'audio': ('voice.wav', recording(), 'audio/wav')})
    assert response.status_code == 409
    assert client.delete(f"{base}/cases/{case['id']}/audio").status_code == 200
    assert not services.artifacts.resolve(directory).exists()


def test_study_delete_removes_all_owned_gridfs_and_local_evidence(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}):
        runs = client.post(base + '/runs', json={'case_id': case['id'], 'conditions': ['B0']}).json()
    with UnitOfWork(services.studies.database) as work:
        for run in runs:
            saved = work.runs.get(run['id'])
            saved.status = RunStatus.COMPLETE
            work.runs.save(saved)
            services.artifacts.write(f"runs/{run['id']}/output.wav", recording())
            services.artifacts.write(f"runs/{run['id']}/tool-exa.log", b'Exa evidence')
    for operation in services.operations.list(limit=None):
        operation.status = 'complete'
        services.operations._save(operation)
    assert client.delete(base).status_code == 204
    assert not any(path.is_file() for path in services.artifacts.root.rglob('*'))
    assert not services.operations.list(limit=None)
    if cloud is not None:
        for namespace in ('artifacts', 'operations'):
            assert not cloud[namespace + '_paths'].rows
            assert not cloud[namespace + '_fixture']
