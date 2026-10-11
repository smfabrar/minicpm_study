import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
const variants = cva("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium", { variants: { variant: { default: "border-transparent bg-primary text-primary-foreground", secondary: "border-transparent bg-secondary text-secondary-foreground", outline: "text-foreground", destructive: "border-transparent bg-destructive/10 text-destructive" } }, defaultVariants: { variant: "secondary" } });
export function Badge({ className, variant, ...props }: React.ComponentProps<"span"> & VariantProps<typeof variants>) { return <span className={cn(variants({ variant }), className)} {...props} />; }
