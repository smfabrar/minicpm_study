import * as React from "react";
import * as Primitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;
export const DialogClose = Primitive.Close;
export function DialogContent({ className, children, ...props }: React.ComponentProps<typeof Primitive.Content>) {
  return <Primitive.Portal>
    <Primitive.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=open]:fade-in" />
    <Primitive.Content className={cn("fixed top-1/2 left-1/2 z-50 flex max-h-[90vh] w-[calc(100%-2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 flex-col gap-5 overflow-y-auto rounded-xl border bg-background p-6 shadow-lg focus:outline-none", className)} {...props}>
      {children}
      <Primitive.Close className="absolute top-4 right-4 rounded-sm text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
        <X className="size-4" />
        <span className="sr-only">Close</span>
      </Primitive.Close>
    </Primitive.Content>
  </Primitive.Portal>;
}
export function DialogHeader({ className, ...props }: React.ComponentProps<"div">) { return <div className={cn("flex flex-col gap-1.5 pr-5", className)} {...props} />; }
export function DialogFooter({ className, ...props }: React.ComponentProps<"div">) { return <div className={cn("flex justify-end gap-2", className)} {...props} />; }
export function DialogTitle(props: React.ComponentProps<typeof Primitive.Title>) { return <Primitive.Title className="text-lg font-semibold tracking-tight" {...props} />; }
export function DialogDescription(props: React.ComponentProps<typeof Primitive.Description>) { return <Primitive.Description className="text-sm text-muted-foreground" {...props} />; }
