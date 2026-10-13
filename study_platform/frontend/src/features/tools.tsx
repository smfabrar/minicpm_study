import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import type { Study, Tool, ToolPayload } from '@/lib/types';
import { api } from '@/lib/api';
import { blankTool, toolPayload, toolSchema } from '@/lib/tool-design';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { ErrorNotice, JsonView } from '@/components/shared';
import { ToolEditor } from './tool-editor';

export function Tools({ study }: { study: Study }) {
  const [editing, setEditing] = useState<(ToolPayload & { id?: string }) | null>(null);
  const [picker, setPicker] = useState(false);
  const library = useQuery({ queryKey: ['tool-library'], queryFn: api.library, enabled: picker });
  const action = useAction();
  const frozen = study.status === 'frozen';
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-sm text-muted-foreground">Granite selects a function and generates arguments from its schema.</p>
      {!frozen && <div className="flex gap-2"><Button variant="outline" onClick={() => setPicker(true)}>Add from library</Button><Button onClick={() => setEditing(blankTool)}>Add tool</Button></div>}
    </div>
    <div className="grid gap-5 lg:grid-cols-2">{study.tools.map((tool: Tool) => <Card key={tool.id}>
      <CardHeader><CardTitle className="font-mono text-base">{tool.name}</CardTitle><CardDescription>{tool.description}</CardDescription></CardHeader>
      <CardContent className="space-y-3"><p className="text-sm text-muted-foreground">{tool.kind} · {tool.delay_ms} ms delay · Failure: {tool.failure}</p><JsonView value={toolSchema(tool)} />
        {tool.kind === 'python' && <details><summary className="cursor-pointer text-sm">Python implementation</summary><pre className="mt-3 max-h-64 overflow-auto rounded bg-muted p-3 text-xs">{tool.python_code}</pre></details>}
      </CardContent>
      <CardFooter className="flex-wrap gap-2">
        {!frozen && <><Button variant="outline" onClick={() => setEditing(tool)}>Edit tool</Button><Button variant="ghost" disabled={action.isPending} onClick={() => action.mutate(() => api.request(`/studies/${study.id}/tools/${tool.id}`, 'DELETE'))}>Remove</Button></>}
        <Button variant="outline" disabled={action.isPending} onClick={() => action.mutate(() => api.request('/tools', 'POST', toolPayload(tool)))}>Save to library</Button>
      </CardFooter>
    </Card>)}</div>
    <Dialog open={editing !== null} onOpenChange={open => { if (!open) setEditing(null); }}><DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl"><DialogHeader><DialogTitle>Tool designer</DialogTitle><DialogDescription>This definition belongs to this study. Freeze the study to preserve its schema, implementation and configuration.</DialogDescription></DialogHeader>
      {editing && <ToolEditor key={editing.id ?? 'new'} initial={editing} save={async definition => { await action.mutateAsync(() => api.request(`/studies/${study.id}/tools${editing.id ? `/${editing.id}` : ''}`, editing.id ? 'PUT' : 'POST', definition)); setEditing(null); }} />}
    </DialogContent></Dialog>
    <Dialog open={picker} onOpenChange={setPicker}><DialogContent className="max-h-[85vh] overflow-y-auto"><DialogHeader><DialogTitle>Add a library tool</DialogTitle><DialogDescription>Adds a copy; later library edits do not change this study.</DialogDescription></DialogHeader><ErrorNotice error={library.error} />
      {library.data?.map(tool => <div key={tool.id} className="rounded-lg border p-3"><p className="font-mono text-sm">{tool.definition.name}</p><p className="my-2 text-sm text-muted-foreground">{tool.definition.description}</p><Button size="sm" disabled={action.isPending || study.tools.some(existing => existing.name === tool.definition.name)} onClick={() => action.mutate(async () => { await api.request(`/studies/${study.id}/tools/attach`, 'POST', { library_id: tool.id }); setPicker(false); })}>Add to study</Button></div>)}
      {library.data?.length === 0 && <p className="text-sm text-muted-foreground">The library is empty. <Link className="underline" to="/tools">Create a tool</Link> first.</p>}
    </DialogContent></Dialog>
  </div>;
}
