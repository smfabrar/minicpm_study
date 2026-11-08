import type { CallerProfile, Settings } from '@/lib/types';
import { comparisonProfiles } from '@/lib/settings';
import { FormField } from '@/components/shared';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function CallerProfiles({ profiles, settings, disabled, onChange }: {
  profiles: CallerProfile[];
  settings: Settings;
  disabled: boolean;
  onChange: (profiles: CallerProfile[]) => void;
}) {
  function edit(index: number, changes: Partial<CallerProfile>) {
    onChange(profiles.map((profile, position) => position === index ? { ...profile, ...changes } : profile));
  }
  return <section className="space-y-4">
    <label className="flex items-start gap-2 text-sm">
      <input type="checkbox" disabled={disabled} checked={profiles.length > 0} onChange={event => {
        onChange(event.target.checked ? comparisonProfiles(settings) : []);
      }} />
      Compare IBM Granite and Qwen in this study
    </label>
    {profiles.length > 0 && <p className="text-sm text-muted-foreground">Each question gets two B0/B1/B2 sets per repetition, using the same input audio. Runs execute sequentially. Only B1 uses the selected caller; B0 and B2 are repeated controls. Caller fields in the runtime settings JSON are used only in single-caller mode.</p>}
    {profiles.map((profile, index) => <div key={profile.backend} className="space-y-3 rounded-lg border p-4">
      <h3 className="font-medium">{profile.backend === 'granite' ? 'IBM Granite' : 'Qwen · thinking disabled'}</h3>
      <div className="grid gap-3 md:grid-cols-3">{(['model', 'revision', 'device'] as const).map(field => <FormField key={field} label={`Caller ${field}`}>
        <Input disabled={disabled} value={profile[field]} onChange={event => edit(index, { [field]: event.target.value })} />
      </FormField>)}</div>
      {profile.backend === 'qwen3' && <FormField label="Qwen weight precision">
        <Select disabled={disabled} value={profile.quantization} onValueChange={quantization => edit(index, { quantization })}>
          <SelectTrigger><SelectValue /></SelectTrigger><SelectContent>
            <SelectItem value="none">Standard · FP16 on GPU / FP32 on CPU</SelectItem>
            <SelectItem value="nf4">4-bit NF4 · CUDA required</SelectItem>
          </SelectContent>
        </Select>
      </FormField>}
    </div>)}
  </section>;
}
