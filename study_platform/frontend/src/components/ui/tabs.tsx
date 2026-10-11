import * as React from "react";
import * as Primitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";
export const Tabs = Primitive.Root;
export function TabsList({ className, ...props }: React.ComponentProps<typeof Primitive.List>) { return <Primitive.List className={cn("inline-flex flex-wrap items-center gap-1 rounded-lg bg-muted p-1", className)} {...props} />; }
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof Primitive.Trigger>) { return <Primitive.Trigger className={cn("inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-xs [&_svg]:size-4", className)} {...props} />; }
export function TabsContent({ className, ...props }: React.ComponentProps<typeof Primitive.Content>) { return <Primitive.Content className={cn("mt-6 focus-visible:outline-none", className)} {...props} />; }
