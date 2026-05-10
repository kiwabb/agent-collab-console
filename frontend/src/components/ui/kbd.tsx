import type { ReactNode } from "react";
import { cn } from "@/lib/utils"

interface KbdProps {
  children: ReactNode
  className?: string
}

export function Kbd({ children, className }: KbdProps) {
  return (
    <kbd
      data-slot="kbd"
      className={cn(
        "inline-flex size-5 items-center justify-center rounded-sm bg-muted/80 px-1 text-[10px] font-mono font-semibold text-muted-foreground ring-1 ring-inset ring-border-subtle",
        className
      )}
    >
      {children}
    </kbd>
  )
}