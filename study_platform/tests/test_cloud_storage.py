"""Adapter boundary checks; real Atlas recovery must also be verified on the server."""
import importlib
import io
import re
import sys
import types
from copy import deepcopy

import pytest


class Collection:
    def __init__(self, name): self.name, self.rows = name, {}
    def find_one(self, query, **kwargs): return deepcopy(self.rows.get(query['_id']))
    def find(self, query, **kwargs):
        prefix = query.get('_id', {}).get('$regex') if isinstance(query.get('_id'), dict) else None
        return [deepcopy(v) for k, v in self.rows.items() if prefix is None or re.search(prefix, k)]
    def replace_one(self, query, document, **kwargs): self.rows[query['_id']] = deepcopy(document)


class FakeDB(dict):
    def __missing__(self, key):
        self[key] = Collection(key)
        return self[key]


class Bucket:
    def __init__(self, database, bucket_name):
        self.files = database.setdefault(bucket_name + '_fixture', {})
    def upload_from_stream(self, name, content):
        from uuid import uuid4
        key = uuid4().hex
        self.files[key] = content
        return key
    def open_download_stream(self, key): return io.BytesIO(self.files[key])
    def delete(self, key): del self.files[key]


def test_gridfs_recovers_empty_cache_and_replaces_existing_content(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'gridfs', types.SimpleNamespace(GridFSBucket=Bucket))
    sys.modules.pop('speech_study.infrastructure.gridfs_store', None)
    module = importlib.import_module('speech_study.infrastructure.gridfs_store')
    db = FakeDB()
    old = module.GridFSArtifactStore(tmp_path / 'old', db)
    old.write('runs/one/output.wav', b'old recording')
    old.write('runs/one/result.json', b'{"status":"complete"}')
    old.write('runs/one/output.wav', b'new recording')
    fresh = module.GridFSArtifactStore(tmp_path / 'fresh', db)
    assert fresh.resolve('runs/one/output.wav').read_bytes() == b'new recording'
    assert fresh.resolve('runs/one').joinpath('result.json').read_bytes() == b'{"status":"complete"}'
    with pytest.raises(ValueError): fresh.resolve('../escape')
    # A local producer explicitly publishes a file; resolving it first would restore old data.
    path = fresh.cache.resolve('runs/one/output.wav')
    path.write_bytes(b'normalized recording')
    fresh.sync('runs/one/output.wav')
    another = module.GridFSArtifactStore(tmp_path / 'another', db)
    assert another.resolve('runs/one/output.wav').read_bytes() == b'normalized recording'
    sys.modules.pop('speech_study.infrastructure.gridfs_store', None)


def test_mongo_unit_of_work_serializes_service_access(monkeypatch):
    import threading
    from speech_study.domain.models import Study
    from speech_contracts import RunSettings
    monkeypatch.setitem(sys.modules, 'pymongo', types.SimpleNamespace(MongoClient=object))
    monkeypatch.setitem(sys.modules, 'pymongo.write_concern', types.SimpleNamespace(WriteConcern=object))
    sys.modules.pop('speech_study.infrastructure.mongo', None)
    module = importlib.import_module('speech_study.infrastructure.mongo')
    class Session:
        def start_transaction(self): pass
        def commit_transaction(self): self.committed = True
        def abort_transaction(self): self.aborted = True
        def end_session(self): self.ended = True
    class Client:
        def start_session(self): return Session()
    database = types.SimpleNamespace(client=Client(), db=FakeDB(), lock=threading.Lock())
    with module.MongoUnitOfWork(database) as work:
        assert not database.lock.acquire(blocking=False)
        study = Study('example', 'Recorded voices', settings=RunSettings())
        work.studies.save(study)
        assert work.studies.get('example') == study
        session = work.session
    assert session.committed and session.ended
    assert database.lock.acquire(blocking=False)
    database.lock.release()
    with pytest.raises(ValueError):
        with module.MongoUnitOfWork(database) as work:
            failed = work.session
            raise ValueError('stop')
    assert failed.aborted and failed.ended
    sys.modules.pop('speech_study.infrastructure.mongo', None)


def test_recorded_voice_is_normalized_attached_and_frozen(tmp_path):
    import wave
    from fastapi.testclient import TestClient
    from speech_study.app import create_app
    data = io.BytesIO()
    with wave.open(data, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(bytes(96000))
    app = create_app(tmp_path)
    client = TestClient(app)
    study = client.post('/api/studies', json={'name': 'Recorded speech'}).json()
    base = '/api/studies/' + study['id']
    case = client.post(base + '/cases', json={'question': 'Where is the seminar?', 'split': 'evaluation', 'category': 'none'}).json()
    url = base + '/cases/' + case['id'] + '/audio?origin=recorded'
    response = client.post(url, files={'audio': ('recording.wav', data.getvalue(), 'audio/wav')})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['audio_origin'] == 'recorded'
    path = app.state.services.artifacts.resolve(saved['audio_path'])
    with wave.open(str(path)) as stream: assert stream.getframerate() == 16000
    assert saved['audio_sha256'] == app.state.services.artifacts.checksum(saved['audio_path'])
    assert study['settings']['granite_device'] == 'cuda:0'
    assert study['settings']['whisper_device_index'] == 0
    assert study['settings']['tts_device'] == 'cuda:0'
    assert study['settings']['reference_audio'].endswith('ref_en_dlc_1.wav')
    assert client.post(base + '/freeze').status_code == 200
    assert client.post(url, files={'audio': ('recording.wav', data.getvalue(), 'audio/wav')}).status_code == 409
