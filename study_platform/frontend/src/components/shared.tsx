import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from 'react';
import { Badge } from './ui/badge';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Alert, AlertDescription, AlertTitle } from './ui/alert';
import { Field, FieldLabel } from './ui/field';
export function Choice({ id, value, options, onChange }: { id?: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <Select value={value} onValueChange={onChange}>
    <SelectTrigger id={id}><SelectValue /></SelectTrigger>
    <SelectContent><SelectGroup>{options.map(option => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectGroup></SelectContent>
  </Select>;
}
export function FormField({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return <Field>
    <FieldLabel htmlFor={id}>{label}</FieldLabel>
    {isValidElement(children) ? cloneElement(children as ReactElement<{ id?: string }>, { id }) : children}
  </Field>;
}
export function Status({ value }: { value: string }) {
  return <Badge variant={['failed', 'interrupted'].includes(value) ? 'destructive' : ['complete', 'frozen', 'correct'].includes(value) ? 'default' : 'secondary'}>{value}</Badge>;
}
export function ErrorNotice({ error }: { error: Error | null }) {
  return error ? <Alert variant="destructive"><AlertTitle>Unable to complete request</AlertTitle><AlertDescription>{error.message}</AlertDescription></Alert> : null;
}
export function JsonView({ value }: { value: unknown }) {
  return <pre className="overflow-auto rounded-lg border bg-muted/40 p-4 text-xs leading-relaxed">{JSON.stringify(value, null, 2)}</pre>;
}
