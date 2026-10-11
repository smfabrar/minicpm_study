import { useState } from 'react';
import { Plus, Pencil, Upload, Volume2, Play, Trash2 } from 'lucide-react';
import type { Study, StudyCase } from '@/lib/types';
import { api } from '@/lib/api';
import { artifactUrl } from '@/lib/utils';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldGroup } from '@/components/ui/field';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Choice, FormField } from '@/components/shared';
const emptyCase = { question: '', category: 'none', split: 'development', expected_answer: '', oracle_result: '', expected_tool: '', expected_arguments: {}, notes: '' };
export function Cases({ study }: {
  study: Study;
}) {
  const action = useAction();
  const [editing, setEditing] = useState<StudyCase | typeof emptyCase | null>(null);
  const [argumentsText, setArgumentsText] = useState('{}');
  const [condition, setCondition] = useState('all');
  const frozen = study.status === 'frozen';
  const base = `/studies/${study.id}`;
  function edit(value: StudyCase | typeof emptyCase) { setArgumentsText(JSON.stringify(value.expected_arguments, null, 2)); setEditing({ ...value }); }
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-muted-foreground">{study.cases.length} cases · one saved audio input reused across all conditions</p>
      <div className="flex gap-2">
        {!frozen && <><Button variant="outline" disabled={action.isPending} onClick={() => action.mutate(async () => {
          for (const item of study.cases.filter(item => !item.audio_path))
            await api.request(`${base}/cases/${item.id}/prepare`, 'POST');
        })}><Volume2 className="size-4" /> Prepare missing audio</Button><Button onClick={() => edit(emptyCase)}><Plus className="size-4" /> Add case</Button></>}
        <div className="w-24">
          <Choice value={condition} options={['all', 'B0', 'B1', 'B2']} onChange={setCondition} />
        </div>
      </div>
    </div>
    {study.cases.length === 0 && <Card>
      <CardContent className="py-12 text-center">
        <p className="mb-4 text-muted-foreground">Add a case or load the proposal's 48-case evaluation template.</p>
        <Button variant="outline" disabled={action.isPending || frozen} onClick={() => action.mutate(() => api.request(`${base}/template`, 'POST'))}>Load proposal template</Button>
      </CardContent>
    </Card>}
    {study.cases.map(item => <Card key={item.id}>
      <CardContent className="space-y-4 pt-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex gap-2">
              <Badge variant="outline">
                {item.category}
              </Badge>
              <Badge variant="secondary">
                {item.split}
              </Badge>
            </div>
            <h3 className="font-medium leading-relaxed">
              {item.question}
            </h3>
            <p className="mt-2 text-sm text-muted-foreground">Expected: {item.expected_answer || 'Not specified'}</p>
          </div>
          {!frozen && <div className="flex gap-1">
            <Button aria-label="Edit case" variant="ghost" size="icon" onClick={() => edit(item)}>
              <Pencil className="size-4" />
            </Button>
            <Button aria-label="Delete case" variant="ghost" size="icon" onClick={() => action.mutate(() => api.request(`${base}/cases/${item.id}`, 'DELETE'))}>
              <Trash2 className="size-4" />
            </Button>
          </div>}
        </div>
        <div className="flex flex-wrap items-center gap-3 border-t pt-4">
          {item.audio_path ? <><audio className="h-9 max-w-full" controls preload="none" src={artifactUrl(item.audio_path)} /><span className="text-xs text-muted-foreground">{item.audio_origin} · {item.audio_sha256?.slice(0, 10)}</span></> : <span className="text-sm text-muted-foreground">Audio not prepared</span>}
          <div className="ml-auto flex gap-2">
            {!frozen && <><Button variant="outline" size="sm" disabled={action.isPending} onClick={() => action.mutate(() => api.request(`${base}/cases/${item.id}/prepare`, 'POST'))}><Volume2 className="size-4" /> TTS</Button><Button asChild variant="outline" size="sm">
              <label><Upload className="size-4" /> WAV<input className="sr-only" type="file" accept="audio/wav,.wav" onChange={event => {
                const file = event.target.files?.[0]; if (file) {
                  const body = new FormData();
                  body.append('audio', file);
                  action.mutate(() => api.request(`${base}/cases/${item.id}/audio`, 'POST', body));
                } event.target.value = '';
              }} /></label>
            </Button></>}
            <Button size="sm" disabled={!item.audio_path || action.isPending} onClick={() => action.mutate(() => api.request(`${base}/runs`, 'POST', { case_id: item.id, conditions: condition === 'all' ? ['B0', 'B1', 'B2'] : [condition] }))}><Play className="size-4" /> Run {condition}</Button>
          </div>
        </div>
      </CardContent>
    </Card>)}
    <Dialog open={editing !== null} onOpenChange={open => {
      if (!open)
        setEditing(null);
    }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {editing && 'id' in editing ? 'Edit case' : 'Add case'}
          </DialogTitle>
          <DialogDescription>The runtime receives audio. Expected answers and oracle facts remain study metadata; only B2 receives its oracle fact.</DialogDescription>
        </DialogHeader>
        {editing && <form onSubmit={event => { event.preventDefault(); action.mutate(async () => { const { question, category, split, expected_answer, oracle_result, expected_tool, notes } = editing; const payload = { question, category, split, expected_answer, oracle_result, expected_tool, notes, expected_arguments: JSON.parse(argumentsText) }; await api.request(`${base}/cases${'id' in editing ? `/${editing.id}` : ''}`, 'id' in editing ? 'PUT' : 'POST', payload); setEditing(null); }); }}>
          <FieldGroup>
            <FormField label="Question / text sent to TTS">
              <Textarea required value={editing.question} onChange={e => setEditing({ ...editing, question: e.target.value })} />
            </FormField>
            <div className="grid grid-cols-2 gap-4">
              <FormField label="Category">
                <Choice value={editing.category} options={['room', 'document', 'calculator', 'none']} onChange={category => setEditing({ ...editing, category })} />
              </FormField>
              <FormField label="Dataset split">
                <Choice value={editing.split} options={['development', 'evaluation']} onChange={split => setEditing({ ...editing, split })} />
              </FormField>
            </div>
            <FormField label="Expected spoken answer">
              <Textarea value={editing.expected_answer} onChange={e => setEditing({ ...editing, expected_answer: e.target.value })} />
            </FormField>
            <FormField label="B2 oracle fact">
              <Textarea value={editing.oracle_result} onChange={e => setEditing({ ...editing, oracle_result: e.target.value })} />
            </FormField>
            <FormField label="Expected tool name">
              <Input value={editing.expected_tool} onChange={e => setEditing({ ...editing, expected_tool: e.target.value })} />
            </FormField>
            <FormField label="Expected arguments (JSON)">
              <Textarea className="font-mono text-xs" value={argumentsText} onChange={e => setArgumentsText(e.target.value)} />
            </FormField>
            <FormField label="Notes">
              <Textarea value={editing.notes} onChange={e => setEditing({ ...editing, notes: e.target.value })} />
            </FormField>
            <Button type="submit" disabled={action.isPending}>Save case</Button>
          </FieldGroup>
        </form>}
      </DialogContent>
    </Dialog>
  </div>;
}
