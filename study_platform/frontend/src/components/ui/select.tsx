import * as React from "react";
import * as Primitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
export const Select = Primitive.Root;
export const SelectGroup = Primitive.Group;
export const SelectValue = Primitive.Value;
export function SelectTrigger({ className, children, ...props }: React.ComponentProps<typeof Primitive.Trigger>) {
  return <Primitive.Trigger className={cn("flex h-10 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 text-sm focus-visible:ring-2 focus-visible:ring-ring", className)} {...props}>
    {children}
    <Primitive.Icon>
      <ChevronDown className="size-4 text-muted-foreground" />
    </Primitive.Icon>
  </Primitive.Trigger>;
}
export function SelectContent({ children, ...props }: React.ComponentProps<typeof Primitive.Content>) {
  return <Primitive.Portal>
    <Primitive.Content position="popper" className="relative z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-y-auto rounded-md border bg-popover text-popover-foreground shadow-md" {...props}>
      <Primitive.Viewport className="p-1">
        {children}
      </Primitive.Viewport>
    </Primitive.Content>
  </Primitive.Portal>;
}
export function SelectItem({ className, children, ...props }: React.ComponentProps<typeof Primitive.Item>) {
  return <Primitive.Item className={cn("relative flex cursor-default items-center rounded-sm py-2 pr-8 pl-2 text-sm outline-none focus:bg-accent data-[disabled]:opacity-50", className)} {...props}>
    <Primitive.ItemText>
      {children}
    </Primitive.ItemText>
    <Primitive.ItemIndicator className="absolute right-2">
      <Check className="size-4" />
    </Primitive.ItemIndicator>
  </Primitive.Item>;
}
