import type { ToolPayload } from './types';

export const blankTool: ToolPayload = {
  name: '',
  description: '',
  parameter: 'query',
  kind: 'python',
  records: {},
  aliases: {},
  delay_ms: 0,
  failure: 'none',
  parameters: { type: 'object', properties: {}, required: [], additionalProperties: false },
  python_code: `def execute(arguments):
    raise NotImplementedError("Write your tool implementation here")
`,
  timeout_seconds: 10,
  ground_arguments: true,
};

export function toolPayload(tool: ToolPayload): ToolPayload {
  return {
    name: tool.name, description: tool.description, parameter: tool.parameter, kind: tool.kind,
    records: tool.records, aliases: tool.aliases, delay_ms: tool.delay_ms, failure: tool.failure,
    parameters: tool.kind === 'python' ? tool.parameters : null,
    python_code: tool.kind === 'python' ? tool.python_code ?? '' : '',
    timeout_seconds: tool.timeout_seconds ?? 10, ground_arguments: tool.ground_arguments ?? true,
  };
}

export function toolSchema(tool: ToolPayload) {
  return { type: 'function', function: { name: tool.name, description: tool.description,
    parameters: tool.parameters ?? { type: 'object', properties: { [tool.parameter]: {
      type: 'string', description: 'Detail explicitly present in the user request', minLength: 1, maxLength: 240,
    } }, required: [tool.parameter], additionalProperties: false },
  } };
}
