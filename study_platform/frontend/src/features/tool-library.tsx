import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { LibraryTool, ToolPayload } from '@/lib/types';
import { api } from '@/lib/api';
import { blankTool, toolSchema } from '@/lib/tool-design';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { ErrorNotice, JsonView } from '@/components/shared';
import { ToolEditor } from './tool-editor';

export function ToolLibraryPage() {
  const query = useQuery({ queryKey: ['tool-library'], queryFn: api.library });
  const [editing, setEditing] = useState<{ id?: string; definition: ToolPayload } | null>(null);
  const [deleting, setDeleting] = useState<LibraryTool | null>(null);
  const action = useAction();
  return <div className="space-y-6">
    <div className="page-heading"><div><h1>Tool library</h1><p className="text-muted-foreground">Design functions once, then add independent copies to any draft study.</p></div>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => setEditing({ definition: blankTool })}>New tool</Button>
      </div>
    </div>
    <p className="rounded-lg border bg-muted/30 p-4 text-sm text-muted-foreground">Whisper transcribes the input. The selected caller chooses an attached function and generates JSON arguments. The runtime validates and executes it, then submits the returned facts to MiniCPM. B0 runs without tools; B2 uses the saved oracle facts.</p>
    <ErrorNotice error={query.error} />
    <div className="grid gap-5 lg:grid-cols-2">
      {query.data?.map(tool => <Card key={tool.id}>
        <CardHeader><CardTitle className="font-mono text-base">{tool.definition.name}</CardTitle><CardDescription>{tool.definition.description}</CardDescription></CardHeader>
        <CardContent className="space-y-3"><p className="text-sm text-muted-foreground">{tool.definition.kind} · {tool.definition.timeout_seconds ?? 10}s timeout</p><JsonView value={toolSchema(tool.definition)} /></CardContent>
        <CardFooter className="gap-2"><Button variant="outline" onClick={() => setEditing(tool)}>Edit</Button><Button variant="ghost" onClick={() => setDeleting(tool)}>Delete template</Button></CardFooter>
      </Card>)}
    </div>
    {query.data?.length === 0 && <p className="text-muted-foreground">No library tools yet. Create a tool with your own parameter schema and Python function.</p>}
    <Dialog open={editing !== null} onOpenChange={open => { if (!open) setEditing(null); }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl"><DialogHeader><DialogTitle>Tool designer</DialogTitle><DialogDescription>Library changes apply to future attachments. Existing study copies keep their saved definition.</DialogDescription></DialogHeader>
        {editing && <ToolEditor key={editing.id ?? editing.definition.name} initial={editing.definition} save={async definition => {
          await action.mutateAsync(() => api.request(`/tools${editing.id ? `/${editing.id}` : ''}`, editing.id ? 'PUT' : 'POST', definition)); setEditing(null);
        }} />}
      </DialogContent>
    </Dialog>
    <Dialog open={deleting !== null} onOpenChange={open => { if (!open) setDeleting(null); }}><DialogContent><DialogHeader><DialogTitle>Delete {deleting?.definition.name}?</DialogTitle><DialogDescription>This removes the library template. Study copies and recorded runs are retained.</DialogDescription></DialogHeader><div className="flex gap-2"><Button variant="outline" onClick={() => setDeleting(null)}>Cancel</Button><Button variant="destructive" disabled={action.isPending} onClick={() => action.mutate(async () => { await api.request(`/tools/${deleting?.id}`, 'DELETE'); setDeleting(null); })}>Delete template</Button></div></DialogContent></Dialog>
  </div>;
}
