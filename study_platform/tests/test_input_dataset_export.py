"""Dataset ZIPs contain current source audio and question text, without run evidence."""

import hashlib
import io
import json
import wave
import zipfile
from pathlib import PurePosixPath
from unittest.mock import patch

from speech_study.infrastructure.unit_of_work import UnitOfWork
from test_audio_deletion import platform as platform


def original_audio(rate=48000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(bytes(rate // 5))
    return output.getvalue()


def prepare(client, base, case):
    response = client.post(f"{base}/cases/{case['id']}/audio?origin=recorded",
                           files={'audio': ('voice.wav', original_audio(), 'audio/wav')})
    assert response.status_code == 200
    return response.json()


def test_dataset_has_numbered_original_and_16khz_audio_with_question_text(platform):
    client, services, base, case, cloud = platform
    client.put(base, json={'name': 'study1'})
    case = prepare(client, base, case)
    question = 'What time is it? — Vad är klockan?'
    second = client.post(base + '/cases', json={'question': question, 'category': 'datetime', 'oracle_mode': 'server_clock'}).json()
    prepare(client, base, second)
    # These neighboring files must not sneak into the input-only ZIP.
    directory = str(PurePosixPath(case['audio_path']).parent)
    services.artifacts.write(directory + '/worker.log', b'preparation log')
    services.artifacts.write('runs/other/output.wav', b'model output')
    with patch('speech_study.services.runs.RuntimeClient.health', side_effect=AssertionError('GPU must not be consulted')):
        response = client.get(base + '/export/inputs')
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        expected = {'study1/manifest.json'}
        for number in (1, 2):
            expected.update(f'study1/{number}/{name}' for name in (
                f'input{number}.wav', f'input{number}_16khz.wav', 'question.txt', 'category.txt'))
            assert archive.read(f'study1/{number}/input{number}.wav') == original_audio()
            with wave.open(io.BytesIO(archive.read(f'study1/{number}/input{number}_16khz.wav')), 'rb') as audio:
                assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
        assert set(archive.namelist()) == expected
        assert archive.read('study1/2/question.txt').decode() == question
        assert archive.read('study1/2/category.txt').decode() == 'datetime'
        manifest = json.loads(archive.read('study1/manifest.json'))
        assert manifest['missing_audio'] == []
        assert [entry['case_id'] for entry in manifest['cases']] == [case['id'], second['id']]
        for entry in manifest['cases']:
            for file in entry['audio_files']:
                assert hashlib.sha256(archive.read(file['path'])).hexdigest() == file['sha256']


def test_unprepared_questions_and_missing_originals_are_reported_without_fake_wavs(platform):
    client, services, base, case, cloud = platform
    client.put(base, json={'name': 'study1'})
    response = client.get(base + '/export/inputs')
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {'study1/manifest.json', 'study1/1/question.txt', 'study1/1/category.txt'}
        manifest = json.loads(archive.read('study1/manifest.json'))
        assert len(manifest['missing_audio']) == 2
        assert all(entry['reason'] == 'not_prepared' for entry in manifest['missing_audio'])
    case = prepare(client, base, case)
    services.artifacts.delete(str(PurePosixPath(case['audio_path']).with_name('original.wav')))
    with zipfile.ZipFile(io.BytesIO(client.get(base + '/export/inputs').content)) as archive:
        assert 'study1/1/input1.wav' not in archive.namelist()
        assert 'study1/1/input1_16khz.wav' in archive.namelist()
        manifest = json.loads(archive.read('study1/manifest.json'))
        assert manifest['missing_audio'] == [{'number': 1, 'path': 'study1/1/input1.wav', 'reason': 'missing_file'}]


def test_checksums_and_pending_audio_deletion_prevent_inconsistent_exports(platform):
    client, services, base, case, cloud = platform
    case = prepare(client, base, case)
    services.artifacts.write(case['audio_path'], b'changed input')
    assert client.get(base + '/export/inputs').status_code == 409
    with UnitOfWork(services.studies.database) as work:
        saved = work.cases.get(case['id'])
        saved.audio_deletion_pending = True
        work.cases.save(saved)
    assert client.get(base + '/export/inputs').status_code == 409


def test_dataset_uses_safe_folder_names_and_recovers_audio_from_gridfs(platform):
    client, services, base, case, cloud = platform
    client.put(base, json={'name': '../../study/one'})
    case = prepare(client, base, case)
    if cloud is not None:
        # Discard the local cache only; cloud files and metadata remain intact.
        services.artifacts.cache.delete(str(PurePosixPath(case['audio_path']).parent))
    response = client.get(base + '/export/inputs')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert 'study_one/1/input1.wav' in archive.namelist()
        assert all(not name.startswith('/') and '..' not in name.split('/') for name in archive.namelist())
        assert archive.read('study_one/1/input1.wav') == original_audio()


def test_tts_export_keeps_original_rate_and_ignores_replaced_input_files(platform):
    client, services, base, case, cloud = platform
    client.put(base, json={'name': 'study1'})
    case = prepare(client, base, case)
    normalized = services.artifacts.resolve(case['audio_path']).read_bytes()
    directory = 'audio/synthesized/tts-fixture'
    services.artifacts.write(directory + '/original.wav', original_audio(24000))
    path = services.artifacts.write(directory + '/input.wav', normalized)
    services.artifacts.write(directory + '/worker.log', b'not dataset content')
    services.studies.attach_audio(case['study_id'], case['id'], path=path,
        checksum=services.artifacts.checksum(path), origin='synthesized', provenance={'model': 'TTS fixture'})
    with zipfile.ZipFile(io.BytesIO(client.get(base + '/export/inputs').content)) as archive:
        assert archive.read('study1/1/input1.wav') == original_audio(24000)
        assert archive.read('study1/1/input1_16khz.wav') == normalized
        assert len(archive.namelist()) == 5
        manifest = json.loads(archive.read('study1/manifest.json'))
        assert manifest['cases'][0]['audio_origin'] == 'synthesized'
