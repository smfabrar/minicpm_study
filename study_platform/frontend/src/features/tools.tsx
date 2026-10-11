import { useState } from 'react';
import type { Study, Tool } from '@/lib/types';
import { api } from '@/lib/api';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldGroup } from '@/components/ui/field';
import { Choice, FormField, JsonView } from '@/components/shared';
const blank = { name: '', description: '', parameter: 'query', kind: 'fixture', records: {}, aliases: {}, delay_ms: 0, failure: 'none' };
export function Tools({ study }: {
  study: Study;
}) {
  const [editing, setEditing] = useState<Tool | typeof blank | null>(null);
  const [records, setRecords] = useState('{}');
  const [aliases, setAliases] = useState('{}');
  const action = useAction();
  const frozen = study.status === 'frozen';
  function edit(value: Tool | typeof blank) { setEditing({ ...value }); setRecords(JSON.stringify(value.records, null, 2)); setAliases(JSON.stringify(value.aliases, null, 2)); }
  return <div className="space-y-5">
    <div className="flex items-center justify-between">
      <p className="text-sm text-muted-foreground">Granite selects a function and generates its required string argument.</p>
      {!frozen && <Button onClick={() => edit(blank)}>Add tool</Button>}
    </div>
    <div className="grid gap-5 lg:grid-cols-2">
      {study.tools.map(tool => <Card key={tool.id}>
        <CardHeader>
          <CardTitle className="font-mono text-base">
            {tool.name}
          </CardTitle>
          <CardDescription>
            {tool.description}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-4 text-sm text-muted-foreground">
            <span>
              {tool.kind}
            </span>
            <span>{tool.delay_ms} ms delay</span>
            <span>Failure: {tool.failure}</span>
          </div>
          <JsonView value={{ type: 'function', function: { name: tool.name, description: tool.description, parameters: { type: 'object', properties: { [tool.parameter]: { type: 'string' } }, required: [tool.parameter], additionalProperties: false } } }} />
        </CardContent>
        {!frozen && <CardFooter className="gap-2">
          <Button variant="outline" onClick={() => edit(tool)}>Edit tool</Button>
          <Button variant="ghost" disabled={action.isPending} onClick={() => action.mutate(() => api.request(`/studies/${study.id}/tools/${tool.id}`, 'DELETE'))}>Remove</Button>
        </CardFooter>}
      </Card>)}
    </div>
    <Dialog open={editing !== null} onOpenChange={open => {
      if (!open)
        setEditing(null);
    }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Tool designer</DialogTitle>
          <DialogDescription>Use deterministic fixtures to control returned facts, aliases, delay, and failure.</DialogDescription>
        </DialogHeader>
        {editing && <form onSubmit={e => { e.preventDefault(); action.mutate(async () => { const { name, description, parameter, kind, delay_ms, failure } = editing; await api.request(`/studies/${study.id}/tools${'id' in editing ? `/${editing.id}` : ''}`, 'id' in editing ? 'PUT' : 'POST', { name, description, parameter, kind, delay_ms, failure, records: JSON.parse(records), aliases: JSON.parse(aliases) }); setEditing(null); }); }}>
          <FieldGroup>
            <FormField label="Function name">
              <Input required pattern="[A-Za-z][A-Za-z0-9_]{0,63}" value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} />
            </FormField>
            <FormField label="Description shown to Granite">
              <Textarea required value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} />
            </FormField>
            <div className="grid grid-cols-2 gap-4">
              <FormField label="Required string parameter">
                <Input required value={editing.parameter} onChange={e => setEditing({ ...editing, parameter: e.target.value })} />
              </FormField>
              <FormField label="Implementation">
                <Choice value={editing.kind} options={['fixture', 'room', 'document', 'calculator']} onChange={kind => setEditing({ ...editing, kind })} />
              </FormField>
            </div>
            <FormField label="Records: lookup key → response (JSON)">
              <Textarea className="min-h-28 font-mono text-xs" value={records} onChange={e => setRecords(e.target.value)} />
            </FormField>
            <FormField label="Aliases: phrase → lookup key (JSON)">
              <Textarea className="font-mono text-xs" value={aliases} onChange={e => setAliases(e.target.value)} />
            </FormField>
            <div className="grid grid-cols-2 gap-4">
              <FormField label="Injected delay in milliseconds">
                <Input type="number" min="0" max="60000" value={editing.delay_ms} onChange={e => setEditing({ ...editing, delay_ms: Number(e.target.value) })} />
              </FormField>
              <FormField label="Failure behavior">
                <Choice value={editing.failure} options={['none', 'error', 'empty']} onChange={failure => setEditing({ ...editing, failure })} />
              </FormField>
            </div>
            <Button disabled={action.isPending}>Save tool</Button>
          </FieldGroup>
        </form>}
      </DialogContent>
    </Dialog>
  </div>;
}
