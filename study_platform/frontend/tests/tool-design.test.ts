import test from 'node:test';
import assert from 'node:assert/strict';
import { blankTool, toolPayload, toolSchema } from '../src/lib/tool-design.ts';

test('new tool is an unnamed Python design with editable source and schema', () => {
  assert.equal(blankTool.name, '');
  assert.equal(blankTool.description, '');
  assert.equal(blankTool.kind, 'python');
  assert.deepEqual(toolSchema(blankTool).function.parameters.required, []);
  assert.match(blankTool.python_code ?? '', /def execute\(arguments\)/);
  assert.match(blankTool.python_code ?? '', /NotImplementedError/);
});

test('payload excludes study identity and clears Python configuration for fixtures', () => {
  const saved = toolPayload({ ...blankTool, kind: 'fixture', name: 'lookup', python_code: 'stale code' });
  assert.equal(saved.parameters, null);
  assert.equal(saved.python_code, '');
  assert.deepEqual(toolSchema(saved).function.parameters.required, ['query']);
  assert.equal('study_id' in saved, false);
  assert.equal('id' in saved, false);
});

test('Python payload preserves user-authored source and custom typed arguments', () => {
  const tool = { ...blankTool, name: 'my_function', python_code: 'def execute(arguments):\n    return str(arguments["count"])\n',
    parameters: { type: 'object', properties: { count: { type: 'integer' } }, required: ['count'], additionalProperties: false } };
  assert.deepEqual(toolPayload(tool).parameters, tool.parameters);
  assert.equal(toolPayload(tool).python_code, tool.python_code);
});
