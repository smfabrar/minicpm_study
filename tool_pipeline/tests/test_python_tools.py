"""Execute authored functions with CPU Python processes, not model fixtures."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from speech_contracts import function_schema, validate_arguments, validate_definition
from tool_pipeline.models.granite import GraniteCaller
from tool_pipeline.telemetry import TraceRecorder
from tool_pipeline.tools import ToolRegistry


def python_tool(source='def execute(arguments):\n    return "UTC time fixture"\n', **changes):
    return {"name": "current_datetime", "description": "Get the current UTC date and time",
            "parameter": "query", "kind": "python", "python_code": source,
            "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            "timeout_seconds": 2, **changes}


def test_zero_argument_python_executes_and_retains_source_and_output(tmp_path):
    source = 'def execute(arguments):\n    print("reading clock")\n    return {"facts": "12:30 UTC", "sources": ["system://clock"]}\n'
    registry = ToolRegistry([python_tool(source)], TraceRecorder(), tmp_path)
    assert function_schema(python_tool(source))["function"]["parameters"]["required"] == []
    result = asyncio.run(registry.execute('current_datetime', {}, 'What time is it?'))
    assert result['facts'] == '12:30 UTC'
    assert result['arguments'] == {}
    assert result['source_sha256'] == hashlib.sha256(source.encode()).hexdigest()
    record = json.loads((tmp_path / result['execution_file']).read_text())
    assert record['status'] == 'complete'
    assert record['elapsed_ms'] > 0
    assert 'reading clock' in (tmp_path / record['log_file']).read_text()
    assert json.loads((tmp_path / record['request_file']).read_text())['source'] == source


def test_multiple_typed_optional_arguments_are_validated_before_execution(tmp_path):
    parameters = {'type': 'object', 'properties': {'count': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                  'enabled': {'type': 'boolean'}, 'suffix': {'type': 'string'}}, 'required': ['count'], 'additionalProperties': False}
    registry = ToolRegistry([python_tool('def execute(arguments):\n    return str(arguments["count"])\n', parameters=parameters)], TraceRecorder(), tmp_path)
    assert asyncio.run(registry.execute('current_datetime', {'count': 2}, 'Count two'))['facts'] == '2'
    for arguments in ({}, {'count': True}, {'count': 9}, {'count': 1, 'extra': 1}, {'count': 1, 'enabled': 'yes'}):
        with pytest.raises(ValueError):
            asyncio.run(registry.execute('current_datetime', arguments, 'Count two'))
    assert len(list(tmp_path.glob('*-request.json'))) == 1


@pytest.mark.parametrize('source,error', [
    ('def execute(arguments):\n    raise LookupError("missing document")\n', 'missing document'),
    ('def execute(arguments):\n    return {"facts": ""}\n', 'non-empty'),
    ('def execute(arguments):\n    return {"facts": "ok", "sources": "file.txt"}\n', 'list of strings'),
])
def test_python_failures_keep_tracebacks_and_execution_record(tmp_path, source, error):
    registry = ToolRegistry([python_tool(source)], TraceRecorder(), tmp_path)
    with pytest.raises(RuntimeError, match=error):
        asyncio.run(registry.execute('current_datetime', {}, 'What time?'))
    record = json.loads(next(tmp_path.glob('*-execution.json')).read_text())
    assert record['status'] == 'failed'
    assert error in record['error']
    assert 'Traceback' in next(tmp_path.glob('*.log')).read_text()


def test_timeout_reaps_tool_process_and_records_failure(tmp_path):
    source = 'import os, time\ndef execute(arguments):\n    print(os.getpid(), flush=True)\n    time.sleep(30)\n    return "late"\n'
    registry = ToolRegistry([python_tool(source, timeout_seconds=0.2)], TraceRecorder(), tmp_path)
    with pytest.raises(TimeoutError, match='timeout'):
        asyncio.run(registry.execute('current_datetime', {}, 'What time?'))
    record = json.loads(next(tmp_path.glob('*-execution.json')).read_text())
    assert record['status'] == 'failed'
    pid = int(next(tmp_path.glob('*.log')).read_text().strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_python_text_file_search_uses_actual_files(tmp_path):
    documents = tmp_path / 'documents'
    documents.mkdir()
    (documents / 'policy.txt').write_text('Lab access opens at 9am.\n')
    source = f'''from pathlib import Path
DOCUMENTS = Path({str(documents)!r})
def execute(arguments):
    query = arguments["query"].casefold()
    hits = [p for p in DOCUMENTS.glob("*.txt") if query in p.read_text().casefold()]
    return {{"facts": "\\n".join(p.read_text() for p in hits), "sources": [p.as_uri() for p in hits]}}
'''
    schema = {'type': 'object', 'properties': {'query': {'type': 'string', 'minLength': 1}}, 'required': ['query'], 'additionalProperties': False}
    registry = ToolRegistry([python_tool(source, parameters=schema)], TraceRecorder(), tmp_path / 'run')
    result = asyncio.run(registry.execute('current_datetime', {'query': 'Lab access'}, 'Search Lab access'))
    assert '9am' in result['facts']
    assert result['sources'] == [(documents / 'policy.txt').as_uri()]
    with pytest.raises(ValueError, match='grounded'):
        asyncio.run(registry.execute('current_datetime', {'query': 'invented'}, 'Search Lab access'))


def test_invalid_definition_is_rejected_without_executing_source(tmp_path):
    marker = tmp_path / 'never'
    source = f'from pathlib import Path\nPath({str(marker)!r}).touch()\ndef execute(arguments):\n    return "ok"\n'
    validate_definition(python_tool(source))
    assert not marker.exists()
    for changes in ({'python_code': 'bad python !!!'}, {'python_code': 'x = 1'},
                    {'parameters': {'type': 'object', '$ref': 'http://host/schema'}},
                    {'parameters': {'type': 'object', 'properties': {}, 'required': ['query']}},
                    {'timeout_seconds': 0}):
        with pytest.raises(ValueError):
            validate_definition(python_tool(**changes))


def test_nested_schema_and_nonfinite_arguments():
    schema = {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': {'type': 'object',
              'properties': {'score': {'type': 'number', 'minimum': 0}}, 'required': ['score']}}}, 'required': ['rows']}
    assert validate_arguments({'rows': [{'score': 1.5}]}, schema)['rows'][0]['score'] == 1.5
    for args in ({'rows': [{'score': -1}]}, {'rows': [{'score': float('nan')}]}, {'rows': 'bad'}):
        with pytest.raises(ValueError):
            validate_arguments(args, schema)


def test_native_caller_can_execute_a_zero_argument_python_tool(tmp_path):
    caller = GraniteCaller.__new__(GraniteCaller)
    caller.trace = TraceRecorder()
    caller.registry = ToolRegistry([python_tool()], caller.trace, tmp_path)
    def generate(messages, schemas):
        assert messages[-1]['content'] == 'What time is it?'
        assert schemas[0]['function']['parameters']['required'] == []
        return '<tool_call>{"name":"current_datetime","arguments":{}}</tool_call>'
    caller.generate = generate
    action = caller.route('What time is it?')
    assert action['kind'] == 'call'
    assert action['arguments'] == {}
    result = asyncio.run(caller.registry.execute(action['tool'], action['arguments'], 'What time is it?'))
    assert result['facts'] == 'UTC time fixture'
