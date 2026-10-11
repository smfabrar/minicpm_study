import * as React from "react";
import { cn } from "@/lib/utils";
export function Empty({ className, ...props }: React.ComponentProps<"div">) { return <div className={cn("flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed p-10 text-center", className)} {...props} />; }
export function EmptyTitle(props: React.ComponentProps<"h3">) { return <h3 className="text-lg font-medium" {...props} />; }
export function EmptyDescription(props: React.ComponentProps<"p">) { return <p className="max-w-md text-sm leading-relaxed text-muted-foreground" {...props} />; }
