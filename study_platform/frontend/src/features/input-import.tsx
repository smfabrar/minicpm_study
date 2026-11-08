import { useState } from 'react';
import { Upload } from 'lucide-react';
import { api } from '@/lib/api';
import type { Study, StudyCase } from '@/lib/types';
import { artifactUrl } from '@/lib/utils';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ErrorNotice, FormField } from '@/components/shared';

interface ImportItem {
  number: string;
  question: string | null;
  category: string | null;
  has_audio: boolean;
  has_original: boolean;
  suggested_case_id: string | null;
  match_reason: string | null;
}
interface Preview { id: string; items: ImportItem[]; existing_cases: StudyCase[] }
interface Selection {
  number: string;
  case_id: string | null;
  text: 'existing' | 'imported';
  audio: 'existing' | 'imported';
  category: 'existing' | 'imported';
  selected: boolean;
}
interface RowResult { number: string; status: 'applied' | 'failed'; case_id?: string; error?: string }

export function InputImport({ study }: { study: Study }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mode, setMode] = useState<'append' | 'replace'>('replace');
  const [selections, setSelections] = useState<Selection[]>([]);
  const [results, setResults] = useState<RowResult[]>([]);
  const action = useAction();
  const base = `/studies/${study.id}/imports`;
  const applied = new Set(results.filter(row => row.status === 'applied').map(row => row.number));

  function defaults(value: Preview, nextMode: 'append' | 'replace') {
    return value.items.map(item => ({ number: item.number, case_id: item.suggested_case_id,
      text: nextMode === 'replace' && !item.question ? 'existing' : 'imported',
      audio: nextMode === 'replace' && !item.has_audio ? 'existing' : 'imported',
      category: nextMode === 'replace' && !item.category ? 'existing' : 'imported',
      selected: nextMode === 'append' ? Boolean(item.question) : Boolean(item.suggested_case_id),
    } as Selection));
  }
  function edit(number: string, changes: Partial<Selection>) {
    setSelections(rows => rows.map(row => row.number === number ? { ...row, ...changes } : row));
  }
  async function close() {
    if (action.isPending) return;
    if (preview) await api.request(`${base}/${preview.id}`, 'DELETE').catch(() => undefined);
    setOpen(false); setPreview(null); setSelections([]); setResults([]); action.reset();
  }
  if (study.status === 'frozen') return null;
  return <>
    <Button variant="outline" onClick={() => setOpen(true)}><Upload className="size-4" /> Import input dataset</Button>
    <Dialog open={open} onOpenChange={value => { if (!value) void close(); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader><DialogTitle>Import input dataset</DialogTitle>
          <DialogDescription>Upload the numbered ZIP exported by this platform, or a partial dataset in the same format. Review choices before saving anything to the study.</DialogDescription>
        </DialogHeader>
        <ErrorNotice error={action.error} />
        <Button asChild variant="outline" disabled={action.isPending || applied.size > 0}>
          <label>Choose dataset ZIP<input type="file" accept=".zip,application/zip" className="sr-only" disabled={action.isPending || applied.size > 0} onChange={event => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (!file) return;
            action.mutate(async () => {
              if (preview) await api.request(`${base}/${preview.id}`, 'DELETE').catch(() => undefined);
              const body = new FormData(); body.append('dataset', file);
              const value = await api.request<Preview>(base, 'POST', body);
              setPreview(value); setResults([]); setSelections(defaults(value, mode));
            });
          }} /></label>
        </Button>
        {preview && <>
          <FormField label="Import mode"><Select value={mode} disabled={action.isPending || applied.size > 0} onValueChange={value => {
            const nextMode = value as 'append' | 'replace'; setMode(nextMode); setSelections(defaults(preview, nextMode)); setResults([]);
          }}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>
            <SelectItem value="replace">Replace selected existing questions</SelectItem>
            <SelectItem value="append">Add as new questions</SelectItem>
          </SelectContent></Select></FormField>
          <p className="text-sm text-muted-foreground">{preview.items.length} imported folders · {preview.existing_cases.length} existing questions. Unselected questions stay unchanged. Review folder-number matches carefully. When text changes, answer/tool annotations are cleared for review. If you keep old audio with new text, confirm they agree.</p>
          {applied.size > 0 && <p role="status" className="text-sm">{applied.size} questions saved. Applied rows are locked; failed rows can be retried.</p>}
          {preview.items.map(item => {
            const selection = selections.find(row => row.number === item.number)!;
            const target = preview.existing_cases.find(row => row.id === selection.case_id);
            const disabled = action.isPending || applied.has(item.number);
            const failure = results.find(row => row.number === item.number && row.status === 'failed');
            return <section key={item.number} className="space-y-3 rounded-lg border p-4">
              <label className="flex items-center gap-2 font-medium"><input type="checkbox" checked={selection.selected} disabled={disabled || (mode === 'append' && !item.question)} onChange={event => edit(item.number, { selected: event.target.checked })} />Folder {item.number}{applied.has(item.number) ? ' · saved' : ''}</label>
              {mode === 'replace' && <FormField label={`Existing question${item.match_reason ? ` · suggested by ${item.match_reason}` : ''}`}>
                <Select value={selection.case_id ?? ''} disabled={disabled} onValueChange={case_id => edit(item.number, { case_id, selected: true })}>
                  <SelectTrigger><SelectValue placeholder="Choose a question to replace" /></SelectTrigger><SelectContent>
                    {preview.existing_cases.map((existing, index) => <SelectItem key={existing.id} value={existing.id}>{index + 1}. {existing.question}</SelectItem>)}
                  </SelectContent>
                </Select>
              </FormField>}
              <div className="grid gap-4 md:grid-cols-2">
                {mode === 'replace' && <div className="space-y-2"><p className="text-sm font-medium">Existing</p><p className="whitespace-pre-wrap text-sm">{target?.question ?? 'No question selected'}</p><p className="text-xs text-muted-foreground">{target?.category}</p>{target?.audio_path ? <audio controls preload="none" className="h-9 max-w-full" src={artifactUrl(target.audio_path)} /> : <p className="text-xs">No existing audio</p>}</div>}
                <div className="space-y-2"><p className="text-sm font-medium">Imported</p><p className="whitespace-pre-wrap text-sm">{item.question ?? 'No question.txt supplied'}</p><p className="text-xs text-muted-foreground">{item.category ?? 'No category supplied'}</p>{item.has_audio ? <><audio controls preload="none" className="h-9 max-w-full" src={`/api${base}/${preview.id}/items/${item.number}/audio/normalized`} /><p className="text-xs">{item.has_original ? 'Original and 16 kHz audio available' : '16 kHz audio only; no original supplied'}</p></> : <p className="text-xs">No imported audio</p>}</div>
              </div>
              {mode === 'replace' && <div className="grid gap-3 md:grid-cols-3">{(['text', 'audio', 'category'] as const).map(field => <FormField key={field} label={field === 'text' ? 'Question text to keep' : `${field === 'audio' ? 'Audio' : 'Category'} to keep`}>
                <Select value={selection[field]} disabled={disabled} onValueChange={value => edit(item.number, { [field]: value as 'existing' | 'imported' })}>
                  <SelectTrigger><SelectValue /></SelectTrigger><SelectContent>
                    <SelectItem value="existing">Keep existing {field}</SelectItem>
                    <SelectItem value="imported" disabled={field === 'text' ? !item.question : field === 'audio' ? !item.has_audio : !item.category}>Use imported {field}</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>)}</div>}
              {failure && <p role="alert" className="text-sm text-destructive">{failure.error}</p>}
            </section>;
          })}
          <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-background py-3">
            <Button variant="outline" disabled={action.isPending} onClick={() => void close()}>Done / close</Button>
            <Button disabled={action.isPending || !selections.some(row => row.selected && !applied.has(row.number))} onClick={() => action.mutate(async () => {
              const selected = selections.filter(row => row.selected && !applied.has(row.number)).map(({ selected: _, ...row }) => row);
              const response = await api.request<{ results: RowResult[] }>(`${base}/${preview.id}/apply`, 'POST', { mode, selections: selected });
              setResults(previous => [...previous.filter(row => !response.results.some(next => next.number === row.number)), ...response.results]);
            })}>{action.isPending ? 'Importing…' : 'Apply selected choices'}</Button>
          </div>
        </>}
      </DialogContent>
    </Dialog>
  </>;
}
