import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus, ArrowUpRight, FlaskConical } from 'lucide-react';
import { api } from '@/lib/api';
import type { Study } from '@/lib/types';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FieldGroup } from '@/components/ui/field';
import { Status, FormField, ErrorNotice } from '@/components/shared';
import { shortDate } from '@/lib/utils';
export function Dashboard() {
  const studies = useQuery({ queryKey: ['studies'], queryFn: api.studies, refetchInterval: 5000 });
  const [open, setOpen] = useState(false);
  const [showTrash, setShowTrash] = useState(false);
  const trash = useQuery({ queryKey: ['trash'], queryFn: api.trash, enabled: showTrash });
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const action = useAction();
  const navigate = useNavigate();
  return <div className="space-y-8">
    <div className="page-heading">
      <div>
        <p className="eyebrow">Research workspace</p>
        <h1>Studies</h1>
        <p className="text-muted-foreground">Design, run, and review speech tool-calling experiments.</p>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger asChild>
          <Button><Plus className="size-4" /> New study</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create a study</DialogTitle>
            <DialogDescription>Start with three tool fixtures and a reproducible configuration.</DialogDescription>
          </DialogHeader>
          <form onSubmit={event => { event.preventDefault(); action.mutate(async () => { const study = await api.request<Study>('/studies', 'POST', { name, description }); setOpen(false); navigate(`/studies/${study.id}`); }); }}>
            <FieldGroup>
              <FormField label="Name">
                <Input required value={name} onChange={event => setName(event.target.value)} placeholder="Room lookup · evaluation 01" />
              </FormField>
              <FormField label="Description">
                <Textarea value={description} onChange={event => setDescription(event.target.value)} />
              </FormField>
              <Button disabled={action.isPending || !name.trim()} type="submit">Create study</Button>
            </FieldGroup>
          </form>
        </DialogContent>
      </Dialog>
    </div>
    <ErrorNotice error={studies.error} />
    <div><Button variant="outline" onClick={() => setShowTrash(!showTrash)}>{showTrash ? 'Hide Trash' : 'Show Trash'}</Button></div>
    {showTrash && <Card><CardHeader><CardTitle>Trash</CardTitle><CardDescription>Deleted studies retain their files and run history.</CardDescription></CardHeader><CardContent className="space-y-3"><ErrorNotice error={trash.error} />{trash.data?.map(study => <div key={study.id} className="flex items-center justify-between gap-4 rounded-lg border p-3"><div><p>{study.name}</p><p className="text-xs text-muted-foreground">{study.case_count} cases · {study.run_count} runs</p></div><Button size="sm" disabled={action.isPending} onClick={() => action.mutate(() => api.request(`/studies/${study.id}/restore`, 'POST'))}>Restore</Button></div>)}{trash.data?.length === 0 && <p className="text-sm text-muted-foreground">Trash is empty.</p>}</CardContent></Card>}
    <div className="grid gap-4 sm:grid-cols-3">
      {[['Studies', studies.data?.length ?? 0], ['Cases', studies.data?.reduce((sum, study) => sum + study.case_count, 0) ?? 0], ['Runs collected', studies.data?.reduce((sum, study) => sum + study.run_count, 0) ?? 0]].map(([label, value]) => <Card key={label}>
        <CardHeader>
          <CardDescription>
            {label}
          </CardDescription>
          <CardTitle className="text-3xl tabular-nums">
            {value}
          </CardTitle>
        </CardHeader>
      </Card>)}
    </div>
    {studies.isPending ? <p className="text-muted-foreground">Loading studies…</p> : studies.data?.length ? <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
      {studies.data.map(study => <Card key={study.id}>
        <CardHeader>
          <div className="flex items-center justify-between">
            <FlaskConical className="size-5 text-primary" />
            <Status value={study.status} />
          </div>
          <CardTitle className="pt-4">
            {study.name}
          </CardTitle>
          <CardDescription>
            {study.description || 'Speech tool-calling study'}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex gap-6 text-sm">
          <span>{study.case_count} cases</span>
          <span>{study.run_count} runs</span>
        </CardContent>
        <CardFooter className="justify-between border-t pt-5">
          <span className="text-xs text-muted-foreground">
            {shortDate(study.updated_at)}
          </span>
          <Button asChild variant="ghost" size="sm">
            <Link to={`/studies/${study.id}`}>Open <ArrowUpRight className="size-4" /></Link>
          </Button>
        </CardFooter>
      </Card>)}
    </div> : <Card>
      <CardContent className="py-16 text-center">
        <FlaskConical className="mx-auto mb-4 size-8 text-muted-foreground" />
        <h2 className="text-lg font-semibold">Your first experiment starts here</h2>
        <p className="mt-2 text-muted-foreground">Create a study, configure tools, and prepare the audio inputs.</p>
      </CardContent>
    </Card>}
  </div>;
}
