import { useMemo, useState, type FormEvent } from 'react';
import { api } from '@/lib/api';
import type { Study } from '@/lib/types';
import { callerSettings, parseStudySettings, selectCaller, verifySavedSettings, type CallerBackend } from '@/lib/settings';
import { useAction } from '@/hooks/use-data';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { FieldGroup } from '@/components/ui/field';
import { ErrorNotice, FormField } from '@/components/shared';

export function StudySettings({ study }: { study: Study }) {
  const [settings, setSettings] = useState(JSON.stringify(study.settings, null, 2));
  const [name, setName] = useState(study.name);
  const [description, setDescription] = useState(study.description);
  const [saved, setSaved] = useState(false);
  const action = useAction();
  const disabled = study.status === 'frozen' || action.isPending;
  const parsedSettings = useMemo(() => {
    try {
      return parseStudySettings(settings);
    } catch {
      return null;
    }
  }, [settings]);
  const caller = callerSettings(parsedSettings ?? {});

  function markEdited() {
    setSaved(false);
    action.reset();
  }

  function changeSettings(value: string) {
    setSettings(value);
    markEdited();
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaved(false);
    action.mutate(async () => {
      const submitted = parseStudySettings(settings);
      await api.request<Study>(`/studies/${study.id}`, 'PUT', { name, description, settings: submitted });
      const persisted = await api.study(study.id);
      verifySavedSettings(submitted, persisted.settings);
      if (persisted.name !== name || persisted.description !== description) {
        throw new Error('Study details were not saved. Reload the study before trying again.');
      }
      setSettings(JSON.stringify(persisted.settings, null, 2));
      setName(persisted.name);
      setDescription(persisted.description);
      setSaved(true);
    });
  }

  return <Card>
    <CardHeader>
      <CardTitle>Reproducible configuration</CardTitle>
      <CardDescription>Set the reference voice, model devices, and time limits before freezing.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-5">
      <ErrorNotice error={action.error} />
      {study.status === 'frozen' && <p className="text-sm text-muted-foreground">This study is frozen. Clone it to edit the configuration.</p>}
      <form onSubmit={save}>
        <FieldGroup>
          <FormField label="Study name">
            <Input disabled={disabled} value={name} onChange={event => { setName(event.target.value); markEdited(); }} />
          </FormField>
          <FormField label="Description">
            <Textarea disabled={disabled} value={description} onChange={event => { setDescription(event.target.value); markEdited(); }} />
          </FormField>
          <FormField label="Reference voice WAV on the pipeline server">
            <Input className="font-mono" disabled={disabled || !parsedSettings}
              value={String(parsedSettings?.reference_audio ?? '')}
              placeholder="/path/on/pipeline-server/reference.wav"
              onChange={event => {
                if (parsedSettings) changeSettings(JSON.stringify({ ...parsedSettings, reference_audio: event.target.value }, null, 2));
              }} />
          </FormField>
          <FormField label="Tool-calling model (B1)">
            <Select disabled={disabled || !parsedSettings} value={caller.backend}
              onValueChange={value => {
                if (parsedSettings) changeSettings(JSON.stringify(selectCaller(parsedSettings, value as CallerBackend), null, 2));
              }}>
              <SelectTrigger aria-label="Tool-calling model (B1)"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="granite">Granite</SelectItem>
                <SelectItem value="qwen3">Qwen3-1.7B · thinking disabled</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <div className="grid gap-4 md:grid-cols-3">
            {(['model', 'revision', 'device'] as const).map(field => <FormField key={field}
              label={`Caller ${field}`}>
              <Input className="font-mono" disabled={disabled || !parsedSettings} value={caller[field]}
                onChange={event => {
                  if (parsedSettings) changeSettings(JSON.stringify({ ...parsedSettings, [`caller_${field}`]: event.target.value }, null, 2));
                }} />
            </FormField>)}
          </div>
          {caller.backend === 'qwen3' && <>
            <FormField label="Caller weight precision">
              <Select disabled={disabled || !parsedSettings} value={caller.quantization}
                onValueChange={value => {
                  if (parsedSettings) changeSettings(JSON.stringify({ ...parsedSettings, caller_quantization: value }, null, 2));
                }}>
                <SelectTrigger aria-label="Caller weight precision"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Standard · FP16 on GPU / FP32 on CPU</SelectItem>
                  <SelectItem value="nf4">4-bit NF4 · CUDA required</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <p className="text-sm text-muted-foreground">
              Qwen uses its native tool template with thinking disabled. 4-bit NF4 reduces weight memory and uses FP16 computation; it requires a CUDA caller device. Run one B1 case to check combined GPU memory before the full matrix.
            </p>
            <p className="text-sm text-muted-foreground">
              Its original weights download on the pipeline server at first use; allow time and disk space for the download.
            </p>
          </>}
          <div className="flex flex-wrap items-center gap-3">
            {study.status === 'draft' && <Button type="submit" disabled={action.isPending}>
              {action.isPending ? 'Saving…' : 'Save configuration'}
            </Button>}
            {saved && <p role="status" className="text-sm text-muted-foreground">Configuration saved and verified.</p>}
          </div>
          <FormField label="Advanced runtime settings (JSON)">
            <Textarea disabled={disabled} className="min-h-[560px] font-mono text-sm" value={settings} onChange={event => changeSettings(event.target.value)} />
          </FormField>
        </FieldGroup>
      </form>
    </CardContent>
  </Card>;
}
