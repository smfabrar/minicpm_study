"""Comparison boundaries and permanent cleanup without models or a real Atlas account."""

import csv
import io
import zipfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from speech_study.app import create_app
from speech_study.domain.models import Review, RunStatus
from speech_study.infrastructure.unit_of_work import UnitOfWork
from test_studies import recording


@pytest.fixture
def platform(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    services = app.state.services
    study = client.post('/api/studies', json={'name': 'Paired comparison'}).json()
    base = '/api/studies/' + study['id']
    case = client.post(base + '/cases', json={'question': 'Where is the robotics seminar?',
        'category': 'room', 'oracle_result': 'Room B742', 'split': 'evaluation'}).json()
    case = client.post(base + '/cases/' + case['id'] + '/audio',
        files={'audio': ('question.wav', recording(), 'audio/wav')}).json()
    yield client, services, base, case
    services.operations.close()


def start(client, base, case, conditions=('B0', 'B1', 'B2')):
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}):
        response = client.post(base + '/runs', json={'case_id': case['id'], 'conditions': conditions})
    assert response.status_code == 202, response.text
    return response.json()


def finish(services):
    with UnitOfWork(services.studies.database) as work:
        for run in work.runs.list_active():
            run.status = RunStatus.COMPLETE
            run.review = Review(verdict='correct' if run.caller_profile['backend'] == 'qwen3' else 'incorrect')
            work.runs.save(run)
    for operation in services.operations.list(limit=None):
        operation.status = 'complete'
        services.operations._save(operation)


def test_both_callers_get_identical_inputs_and_independent_results(platform):
    client, services, base, case = platform
    profiles = client.get(base).json()['caller_profiles']
    assert {profile['backend'] for profile in profiles} == {'granite', 'qwen3'}
    assert client.post(base + '/freeze').status_code == 200
    runs = start(client, base, case)
    assert len(runs) == 6
    assert len({run['comparison_id'] for run in runs}) == 1
    assert len({run['request']['audio_sha256'] for run in runs}) == 1
    for condition in ('B0', 'B1', 'B2'):
        pair = [run for run in runs if run['condition'] == condition]
        assert {run['caller_profile']['backend'] for run in pair} == {'granite', 'qwen3'}
        for run in pair:
            assert run['request']['settings']['caller_backend'] == run['caller_profile']['backend']
            assert run['snapshot']['caller_profiles'] == profiles
            if condition != 'B2':
                assert 'oracle_result' not in run['request']
    finish(services)
    report = client.get(base + '/analysis').json()
    by_backend = {group['profile']['backend']: group['conditions'] for group in report['callers']}
    assert all(row['spoken_accuracy'] == 1 for row in by_backend['qwen3'])
    assert all(row['spoken_accuracy'] == 0 for row in by_backend['granite'])
    with zipfile.ZipFile(io.BytesIO(client.get(base + '/export').content)) as archive:
        rows = list(csv.DictReader(io.StringIO(archive.read('runs.csv').decode())))
        assert len(rows) == 6
        assert {row['caller_backend'] for row in rows} == {'granite', 'qwen3'}
        assert len({row['comparison_id'] for row in rows}) == 1


def test_matrix_repetitions_and_saved_profiles_survive_restart_and_clone(platform, tmp_path):
    client, services, base, case = platform
    profiles = client.get(base).json()['caller_profiles']
    profiles[1].update(revision='pinned-qwen', quantization='nf4')
    assert client.put(base, json={'caller_profiles': profiles, 'settings': {'repetitions': 2}}).status_code == 200
    assert client.post(base + '/freeze').status_code == 200
    with patch('speech_study.services.runs.RuntimeClient.health', return_value={}) as health:
        response = client.post(base + '/matrix')
    assert response.status_code == 202
    runs = response.json()
    assert len(runs) == 12
    assert health.call_count == 1
    assert {run['repetition'] for run in runs} == {1, 2}
    assert len({run['comparison_id'] for run in runs}) == 2
    qwen = [run for run in runs if run['caller_profile']['backend'] == 'qwen3']
    assert all(run['request']['settings']['caller_revision'] == 'pinned-qwen' for run in qwen)
    clone = client.post(base + '/clone').json()
    assert clone['caller_profiles'] == profiles
    assert TestClient(create_app(tmp_path)).get(base).json()['caller_profiles'] == profiles
    assert client.put(base, json={'caller_profiles': []}).status_code == 409


def test_legacy_single_caller_and_profile_validation(platform):
    client, services, base, case = platform
    assert client.put(base, json={'caller_profiles': []}).status_code == 200
    assert len(start(client, base, case, ['B1'])) == 1
    assert client.put(base, json={'caller_profiles': [{'backend': 'qwen3'}]}).status_code == 400


def test_legacy_trash_can_be_permanently_removed(platform):
    client, services, base, case = platform
    with UnitOfWork(services.studies.database) as work:
        study = work.studies.get(base.rsplit('/', 1)[1])
        study.deleted_at = '2026-11-01T00:00:00+00:00'
        work.studies.save(study)
    assert len(client.get('/api/studies?deleted=true').json()) == 1
    assert client.delete(base).status_code == 204
    assert client.get('/api/studies?deleted=true').json() == []
    assert not services.artifacts.resolve(case['audio_path']).exists()


def test_delete_removes_history_files_and_operation_records(platform):
    client, services, base, case = platform
    runs = start(client, base, case)
    finish(services)
    for run in runs:
        services.artifacts.write(f"runs/{run['id']}/tool-web_search.log", b'Exa evidence')
    # Replacing question/audio must not leave its previous recording unowned.
    client.put(base + '/cases/' + case['id'], json={'question': 'Changed question'})
    assert client.delete(base).status_code == 204
    assert client.get(base).status_code == 404
    assert client.get('/api/studies?deleted=true').json() == []
    assert not services.artifacts.resolve(case['audio_path']).exists()
    assert not any(services.artifacts.root.rglob('*.*'))
    assert services.operations.list(limit=None) == []
    for run in runs:
        assert client.get('/api/runs/' + run['id']).status_code == 404
    with services.studies.database.connect() as connection:
        for table in ('studies', 'cases', 'tools', 'runs'):
            assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


def test_failed_cleanup_is_retryable_after_restart(platform, tmp_path):
    client, services, base, case = platform
    with patch.object(services.artifacts, 'delete', side_effect=OSError('storage unavailable')):
        with pytest.raises(OSError):
            client.delete(base)
    trashed = client.get('/api/studies?deleted=true').json()[0]
    assert trashed['purge_plan']['artifacts']
    assert client.post(base + '/restore').status_code == 409
    restarted = TestClient(create_app(tmp_path))
    assert restarted.delete(base).status_code == 204
    assert restarted.get('/api/studies?deleted=true').json() == []
    assert not services.artifacts.resolve(case['audio_path']).exists()
