import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
const alertVariants = cva("relative rounded-lg border p-4 text-sm", {
  variants: { variant: { default: "bg-card text-card-foreground", destructive: "border-destructive/30 bg-destructive/5 text-destructive" } },
  defaultVariants: { variant: "default" },
});
export function Alert({ className, variant, ...props }: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />;
}
export function AlertTitle(props: React.ComponentProps<"h5">) { return <h5 className="mb-1 font-medium" {...props} />; }
export function AlertDescription(props: React.ComponentProps<"div">) { return <div className="text-sm leading-relaxed" {...props} />; }
