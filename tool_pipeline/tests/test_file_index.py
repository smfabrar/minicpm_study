"""Filename lookup in configured text paths, without host files or model inference."""

import asyncio
import json

import pytest

from tool_pipeline.file_index import FileIndex
from tool_pipeline.telemetry import TraceRecorder
from tool_pipeline.tools import ToolRegistry


@pytest.mark.parametrize('filename', ['project-report.pdf', 'PROJECT-REPORT.PDF',
                                      'project report dot P D F', 'project_report.pdf'])
def test_filename_lookup_returns_virtual_folder_and_full_path(filename):
    index = FileIndex(['/research/drafts/project-report.pdf', '/finance/budget.xlsx'])
    result = index.search(filename)
    assert result['evidence']['matches'] == [{'filename': 'project-report.pdf',
        'folder': '/research/drafts', 'path': '/research/drafts/project-report.pdf', 'similarity': 1.0}]
    assert result['facts'].startswith('Found 1 exact filename match.')
    assert 'Full path: /research/drafts/project-report.pdf.' in result['facts']
    assert result['evidence']['match_type'] == 'exact'
    assert result['evidence']['index_kind'] == 'virtual'


@pytest.mark.parametrize('filename', ['report', 'missing.pdf', 'unrelated holiday photo'])
def test_distant_and_overly_broad_names_return_not_found(filename):
    result = FileIndex(['/research/drafts/project-report.pdf']).search(filename)
    assert result['evidence']['match_type'] == 'not_found'
    assert result['evidence']['matches'] == []
    assert result['facts'].startswith('No file found with the name')


@pytest.mark.parametrize('filename', ['bugdet.xlsx', 'budget', 'budjet dot xlsx'])
def test_misheard_names_and_missing_extensions_are_labelled_approximate(filename):
    result = FileIndex(['/finance/budget.xlsx', '/drafts/report.pdf']).search(filename)
    assert result['evidence']['match_type'] == 'approximate'
    assert result['evidence']['matches'][0]['path'] == '/finance/budget.xlsx'
    assert result['evidence']['matches'][0]['similarity'] >= 0.8
    assert 'possible approximate filename match' in result['facts']
    assert 'No exact filename match' in result['facts']


def test_exact_match_excludes_similar_filenames_even_with_a_stem_match():
    result = FileIndex(['/drafts/budget.xlsx', '/drafts/budget.xls', '/drafts/budget.xlsx.pdf']).search('budget.xlsx')
    assert result['evidence']['match_type'] == 'exact'
    assert [item['filename'] for item in result['evidence']['matches']] == ['budget.xlsx']


def test_different_extension_can_only_return_an_approximate_candidate():
    result = FileIndex(['/drafts/project-report.pdf']).search('project-report.docx')
    assert result['evidence']['match_type'] == 'approximate'
    assert result['evidence']['matches'][0]['filename'] == 'project-report.pdf'
    assert result['evidence']['matches'][0]['similarity'] < 1


def test_approximate_matches_are_ranked_and_keep_multiple_locations():
    index = FileIndex(['/b/budget.xlsx', '/a/budget.xlsx', '/c/budgets.xlsx'])
    result = index.search('budjet.xlsx')
    matches = result['evidence']['matches']
    assert [item['path'] for item in matches] == ['/a/budget.xlsx', '/b/budget.xlsx', '/c/budgets.xlsx']
    assert matches[0]['similarity'] == matches[1]['similarity'] > matches[2]['similarity']
    assert result['evidence']['match_type'] == 'approximate'


def test_threshold_is_recorded_and_controls_the_fuzzy_fallback():
    result = FileIndex(['/finance/budget.xlsx'], similarity_threshold=0.95).search('bugdet.xlsx')
    assert result['evidence']['match_type'] == 'not_found'
    assert result['evidence']['similarity_threshold'] == 0.95
    assert result['evidence']['implementation'] == 'filename-index-v2'


@pytest.mark.parametrize('threshold', [0, -0.1, 1.1, float('nan')])
def test_invalid_thresholds_are_rejected(threshold):
    with pytest.raises(ValueError, match='similarity threshold'):
        FileIndex([], similarity_threshold=threshold)


@pytest.mark.parametrize('filename', ['', '...', ' ' * 3, 'a' * 241, None])
def test_invalid_filename_arguments_remain_errors(filename):
    with pytest.raises(ValueError):
        FileIndex(['/finance/budget.xlsx']).search(filename)


def test_empty_index_returns_not_found():
    result = FileIndex([]).search('budget.xlsx')
    assert result['evidence']['match_type'] == 'not_found'
    assert result['evidence']['matches'] == []


def test_duplicate_filenames_return_all_distinct_locations():
    result = FileIndex(['/drafts/report.pdf', '/final/report.pdf', '/final/report.pdf']).search('report.pdf')
    assert [match['folder'] for match in result['evidence']['matches']] == ['/drafts', '/final']
    assert result['facts'].startswith('Found 2 exact filename matches.')


@pytest.mark.parametrize(('filename', 'match_type'), [
    ('project-report.pdf', 'exact'),
    ('project-repot.pdf', 'approximate'),
    ('holiday.jpg', 'not_found'),
])
def test_file_locator_executes_through_the_python_tool_runner(tmp_path, filename, match_type):
    definition = {
        'name': 'document_search', 'description': 'Find a filename in a configured index',
        'kind': 'python', 'parameter': 'filename', 'ground_arguments': False,
        'parameters': {'type': 'object', 'properties': {'filename': {'type': 'string', 'minLength': 1}},
                       'required': ['filename'], 'additionalProperties': False},
        'python_code': "from tool_pipeline.file_index import FileIndex\nFILES = ['/research/drafts/project-report.pdf']\ndef execute(arguments):\n    return FileIndex(FILES).search(arguments['filename'])\n",
    }
    registry = ToolRegistry([definition], TraceRecorder(), tmp_path)
    result = asyncio.run(registry.execute('document_search', {'filename': filename},
                                         'Which folder is project report dot PDF in?'))
    assert result['arguments'] == {'filename': filename}
    assert result['evidence']['match_type'] == match_type
    if match_type != 'not_found':
        assert result['evidence']['matches'][0]['folder'] == '/research/drafts'
    saved = json.loads((tmp_path / result['execution_file']).read_text())
    assert saved['status'] == 'complete'
    assert saved['result']['evidence'] == result['evidence']
