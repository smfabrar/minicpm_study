"""Preview/merge imports and partial retries with local and GridFS artifact stores."""

import io
import zipfile
from pathlib import PurePosixPath
from unittest.mock import patch

from test_audio_deletion import platform as platform, attach
from test_input_dataset_export import original_audio
from test_studies import recording
from test_comparison_and_deletion import finish, start


def dataset(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def preview(client, base, content):
    response = client.post(base + '/imports', files={'dataset': ('inputs.zip', content, 'application/zip')})
    assert response.status_code == 200, response.text
    return response.json()


def apply(client, base, value, mode, selections):
    response = client.post(f"{base}/imports/{value['id']}/apply", json={'mode': mode, 'selections': selections})
    assert response.status_code == 200, response.text
    return response.json()


def selection(number='1', case_id=None, **choices):
    return {'number': number, 'case_id': case_id, 'text': 'imported', 'audio': 'imported',
            'category': 'imported', **choices}


def test_roundtrip_preview_does_not_upload_until_apply_and_append_is_idempotent(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    exported = client.get(base + '/export/inputs').content
    before = len(cloud['artifacts_fixture']) if cloud is not None else None
    value = preview(client, base, exported)
    assert value['items'][0]['suggested_case_id'] == case['id']
    assert value['items'][0]['match_reason'] == 'case ID'
    assert len(client.get(base).json()['cases']) == 1
    if cloud is not None:
        assert len(cloud['artifacts_fixture']) == before
    assert client.get(f"{base}/imports/{value['id']}/items/1/audio/normalized").content == services.artifacts.resolve(case['audio_path']).read_bytes()
    result = apply(client, base, value, 'append', [selection()])
    assert result['applied'] == 1
    cases = client.get(base).json()['cases']
    assert len(cases) == 2 and cases[1]['audio_origin'] == 'imported'
    assert cases[1]['audio_sha256'] == case['audio_sha256']
    assert cases[1]['audio_path'] == case['audio_path']  # Exact duplicates share stored bytes.
    assert apply(client, base, value, 'append', [selection()])['applied'] == 1
    assert len(client.get(base).json()['cases']) == 2
    if cloud is not None:
        assert len(cloud['artifacts_fixture']) == before


def test_partial_zip_replaces_one_of_48_or_appends_without_touching_other_questions(platform):
    client, services, base, case, cloud = platform
    for number in range(2, 49):
        client.post(base + '/cases', json={'question': f'Question {number}'})
    original_cases = client.get(base).json()['cases']
    content = dataset({'study/12/question.txt': 'Imported question twelve',
                       'study/12/input12.wav': original_audio()})
    value = preview(client, base, content)
    target = original_cases[11]
    assert value['items'][0]['suggested_case_id'] == target['id']
    assert value['items'][0]['match_reason'] == 'folder number'
    result = apply(client, base, value, 'replace', [selection('12', target['id'], text='existing', category='existing')])
    assert result['applied'] == 1
    cases = client.get(base).json()['cases']
    assert len(cases) == 48 and cases[11]['question'] == 'Question 12'
    assert cases[11]['audio_path']
    assert cases[0] == original_cases[0] and cases[-1] == original_cases[-1]
    other_preview = preview(client, base, content)
    assert apply(client, base, other_preview, 'append', [selection('12')])['applied'] == 1
    assert len(client.get(base).json()['cases']) == 49


def test_replace_text_and_audio_choices_are_independent_and_reclaim_unused_audio(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    value = preview(client, base, dataset({'1/question.txt': 'A new question', '1/category.txt': 'web'}))
    result = apply(client, base, value, 'replace', [selection(case_id=case['id'], audio='existing')])
    assert result['applied'] == 1
    saved = client.get(base).json()['cases'][0]
    assert saved['question'] == 'A new question' and saved['category'] == 'web'
    assert saved['audio_path'] == case['audio_path']
    old_directory = str(PurePosixPath(saved['audio_path']).parent)
    value = preview(client, base, dataset({'1/input1.wav': original_audio()}))
    result = apply(client, base, value, 'replace', [selection(case_id=case['id'], text='existing', category='existing')])
    assert result['applied'] == 1
    saved = client.get(base).json()['cases'][0]
    assert saved['question'] == 'A new question' and saved['audio_path'] != case['audio_path']
    assert not services.artifacts.resolve(old_directory).exists()


def test_imported_audio_does_not_delete_audio_used_by_saved_runs(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    runs = start(client, base, case, ['B0'])
    finish(services)
    value = preview(client, base, dataset({'1/input1.wav': original_audio()}))
    assert apply(client, base, value, 'replace', [selection(case_id=case['id'], text='existing', category='existing')])['applied'] == 1
    assert services.artifacts.resolve(case['audio_path']).is_file()
    assert client.get('/api/runs/' + runs[0]['id']).json()['request']['audio_path'] == case['audio_path']


def test_partial_failures_can_retry_without_duplicating_already_saved_rows(platform):
    client, services, base, case, cloud = platform
    value = preview(client, base, dataset({'1/question.txt': 'Text-only question',
                                         '2/input2_16khz.wav': recording()}))
    choices = [selection('1'), selection('2')]
    result = apply(client, base, value, 'append', choices)
    assert [row['status'] for row in result['results']] == ['applied', 'failed']
    apply(client, base, value, 'append', choices)
    assert len(client.get(base).json()['cases']) == 2


def test_changed_question_after_preview_and_frozen_study_are_not_overwritten(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    content = dataset({'1/question.txt': 'Replacement'})
    value = preview(client, base, content)
    client.put(base + '/cases/' + case['id'], json={'question': case['question'], 'split': 'evaluation', 'notes': 'Changed while preview open'})
    result = apply(client, base, value, 'replace', [selection(case_id=case['id'], audio='existing', category='existing')])
    assert result['applied'] == 0 and 'changed after preview' in result['results'][0]['error']
    assert client.post(base + '/freeze').status_code == 200
    assert client.post(base + '/imports', files={'dataset': ('inputs.zip', content)}).status_code == 409
    assert client.post(f"{base}/imports/{value['id']}/apply", json={'mode': 'append', 'selections': [selection()]}).status_code == 409


def test_malformed_archives_are_rejected_and_staged_files_are_cleaned_up(platform):
    client, services, base, case, cloud = platform
    for files in ({'../question.txt': 'escape'}, {'1/question.txt': 'Hello', '1/input1.wav': b'not a WAV'},
                  {'1/question.txt': 'Hello', '2/category.txt': 'invalid-category'}):
        response = client.post(base + '/imports', files={'dataset': ('bad.zip', dataset(files))})
        assert response.status_code == 400, response.text
        assert not list(services.input_imports.repository.store.root.iterdir())
    value = preview(client, base, dataset({'1/question.txt': 'Good input'}))
    assert client.delete(f"{base}/imports/{value['id']}").status_code == 204
    assert not list(services.input_imports.repository.store.root.iterdir())
    preview(client, base, dataset({'1/question.txt': 'Good input'}))
    assert client.delete(base).status_code == 204
    assert not list(services.input_imports.repository.store.root.iterdir())


def test_normalized_only_audio_is_preserved_without_inventing_an_original(platform):
    client, services, base, case, cloud = platform
    content = dataset({'4/question.txt': 'Imported without original',
                       '4/input4_16khz.wav': recording()})
    value = preview(client, base, content)
    assert not value['items'][0]['has_original']
    result = apply(client, base, value, 'append', [selection('4')])
    assert result['applied'] == 1
    imported = client.get(base).json()['cases'][-1]
    assert services.artifacts.resolve(imported['audio_path']).read_bytes() == recording()
    original = str(PurePosixPath(imported['audio_path']).with_name('original.wav'))
    assert not services.artifacts.resolve(original).exists()


def test_cleanup_failure_retries_without_duplicate_rows_or_losing_new_audio(platform):
    client, services, base, case, cloud = platform
    case = attach(client, base, case)
    old_directory = str(PurePosixPath(case['audio_path']).parent)
    value = preview(client, base, dataset({'1/input1.wav': original_audio()}))
    choices = [selection(case_id=case['id'], text='existing', category='existing')]
    with patch.object(services.artifacts, 'delete', side_effect=OSError('Temporary cloud failure')):
        result = apply(client, base, value, 'replace', choices)
    assert result['applied'] == 0 and 'New input saved' in result['results'][0]['error']
    saved = client.get(base).json()['cases'][0]
    assert services.artifacts.resolve(saved['audio_path']).is_file()
    assert saved['input_import']['cleanup_directory'] == old_directory
    assert apply(client, base, value, 'replace', choices)['applied'] == 1
    assert len(client.get(base).json()['cases']) == 1
    assert not services.artifacts.resolve(old_directory).exists()


def test_retry_does_not_report_success_after_imported_question_was_edited(platform):
    client, services, base, case, cloud = platform
    value = preview(client, base, dataset({'1/question.txt': 'First import'}))
    result = apply(client, base, value, 'append', [selection()])
    identifier = result['results'][0]['case_id']
    client.put(base + '/cases/' + identifier, json={'question': 'Edited after import'})
    retried = apply(client, base, value, 'append', [selection()])
    assert retried['applied'] == 0
    assert 'edited afterward' in retried['results'][0]['error']
    assert len(client.get(base).json()['cases']) == 2
