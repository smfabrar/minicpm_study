import * as React from "react";
import { cn } from "@/lib/utils";
export function FieldGroup({ className, ...props }: React.ComponentProps<"div">) { return <div data-slot="field-group" className={cn("flex flex-col gap-5", className)} {...props} />; }
export function Field({ className, ...props }: React.ComponentProps<"div">) { return <div data-slot="field" className={cn("flex flex-col gap-2 data-[invalid=true]:text-destructive", className)} {...props} />; }
export function FieldLabel({ className, ...props }: React.ComponentProps<"label">) { return <label className={cn("text-sm font-medium", className)} {...props} />; }
export function FieldDescription({ className, ...props }: React.ComponentProps<"p">) { return <p className={cn("text-xs leading-relaxed text-muted-foreground", className)} {...props} />; }
