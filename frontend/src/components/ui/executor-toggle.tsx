"use client";

import { cn } from "@/lib/utils";

type Executor = "codex" | "claude";

interface ExecutorToggleProps {
  value: Executor;
  onChange: (value: Executor) => void;
  codexLabel: string;
  claudeLabel: string;
  className?: string;
}

export function ExecutorToggle({
  value,
  onChange,
  codexLabel,
  claudeLabel,
  className,
}: ExecutorToggleProps) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 gap-1 p-1 rounded-xl border border-border-subtle bg-surface-input/50",
        className,
      )}
    >
      <button
        type="button"
        onClick={() => onChange("codex")}
        className={cn(
          "h-8 rounded-lg text-[10px] font-bold uppercase tracking-[0.12em] transition-all",
          value === "codex"
            ? "bg-brand text-background shadow-sm"
            : "text-text-muted hover:text-foreground hover:bg-surface-hover",
        )}
      >
        {codexLabel}
      </button>
      <button
        type="button"
        onClick={() => onChange("claude")}
        className={cn(
          "h-8 rounded-lg text-[10px] font-bold uppercase tracking-[0.12em] transition-all",
          value === "claude"
            ? "bg-brand text-background shadow-sm"
            : "text-text-muted hover:text-foreground hover:bg-surface-hover",
        )}
      >
        {claudeLabel}
      </button>
    </div>
  );
}
