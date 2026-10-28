import { useState } from 'react';
import type { ToolPayload } from '@/lib/types';
import { toolPayload, toolSchema } from '@/lib/tool-design';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldGroup } from '@/components/ui/field';
import { Choice, FormField, JsonView, ErrorNotice } from '@/components/shared';

export function ToolEditor({ initial, save }: { initial: ToolPayload; save: (tool: ToolPayload) => Promise<unknown> }) {
  const [tool, setTool] = useState({ ...initial });
  const [records, setRecords] = useState(JSON.stringify(initial.records, null, 2));
  const [aliases, setAliases] = useState(JSON.stringify(initial.aliases, null, 2));
  const [parameters, setParameters] = useState(JSON.stringify(initial.parameters ?? { type: 'object', properties: {}, required: [], additionalProperties: false }, null, 2));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const python = tool.kind === 'python';
  return <form onSubmit={async event => {
    event.preventDefault(); setPending(true); setError(null);
    try {
      await save(toolPayload({ ...tool, records: python ? {} : JSON.parse(records),
        aliases: python ? {} : JSON.parse(aliases), parameters: python ? JSON.parse(parameters) : null }));
    } catch (cause) { setError(cause instanceof Error ? cause : new Error(String(cause))); }
    finally { setPending(false); }
  }}>
    <fieldset disabled={pending}>
      <FieldGroup>
        <FormField label="Function name"><Input required pattern="[A-Za-z][A-Za-z0-9_]{0,63}" value={tool.name} onChange={e => setTool({ ...tool, name: e.target.value })} /></FormField>
        <FormField label="Description shown to the tool caller"><Textarea required value={tool.description} onChange={e => setTool({ ...tool, description: e.target.value })} /></FormField>
        <FormField label="Implementation"><Choice value={tool.kind} options={['fixture', 'room', 'document', 'calculator', 'python']} onChange={kind => setTool({ ...tool, kind })} /></FormField>
        {python ? <>
          <FormField label="Parameters (JSON Schema)"><Textarea className="min-h-40 font-mono text-xs" value={parameters} onChange={e => setParameters(e.target.value)} /></FormField>
          <p className="text-xs text-muted-foreground">Use an object with empty properties and required lists for a tool with no arguments. Supports objects, arrays, strings, numbers, integers, booleans, null, enum, const, bounds and patterns.</p>
          <FormField label="Python function"><Textarea required spellCheck={false} className="min-h-72 font-mono text-xs" value={tool.python_code ?? ''} onChange={e => setTool({ ...tool, python_code: e.target.value })} /></FormField>
          <p className="text-xs text-muted-foreground">Define execute(arguments). Return text or {'{ "facts": "…", "sources": ["…"] }'}. Runs on the runtime server with its Python packages and account access. Source is copied into each run; stdout and errors are logged.</p>
          <FormField label="Execution timeout (seconds)"><Input type="number" min="0.1" max="120" step="0.1" value={tool.timeout_seconds ?? 10} onChange={e => setTool({ ...tool, timeout_seconds: Number(e.target.value) })} /></FormField>
        </> : <>
          <FormField label="Required string parameter"><Input required value={tool.parameter} onChange={e => setTool({ ...tool, parameter: e.target.value })} /></FormField>
          {tool.kind !== 'calculator' && <>
            <FormField label="Records: lookup key → response (JSON)"><Textarea className="min-h-28 font-mono text-xs" value={records} onChange={e => setRecords(e.target.value)} /></FormField>
            <FormField label="Aliases: phrase → lookup key (JSON)"><Textarea className="font-mono text-xs" value={aliases} onChange={e => setAliases(e.target.value)} /></FormField>
            {tool.kind === 'document' && <p className="text-xs text-muted-foreground">This searches the records above. Choose Python and write a function to read actual files on the runtime server.</p>}
          </>}
        </>}
        {tool.kind !== 'calculator' && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={tool.ground_arguments ?? true} onChange={e => setTool({ ...tool, ground_arguments: e.target.checked })} />Require string arguments to appear in the input transcript</label>}
        <div className="grid grid-cols-2 gap-4">
          <FormField label="Injected delay (milliseconds)"><Input type="number" min="0" max="60000" value={tool.delay_ms} onChange={e => setTool({ ...tool, delay_ms: Number(e.target.value) })} /></FormField>
          <FormField label="Failure behavior"><Choice value={tool.failure} options={['none', 'error', 'empty']} onChange={failure => setTool({ ...tool, failure })} /></FormField>
        </div>
        {!python && <JsonView value={toolSchema(tool)} />}
        <ErrorNotice error={error} />
        <Button type="submit">{pending ? 'Saving…' : 'Save tool'}</Button>
      </FieldGroup>
    </fieldset>
  </form>;
}
