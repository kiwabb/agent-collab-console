"use client";

import { cn } from "@/lib/utils";

/**
 * One row in a Codex/Claude run log. Mirrors the screenshot:
 *
 *   04:12.1   sys    codex exec --json --thread thr_8a2 'Wire CodexAdapter…'
 *   04:11.9   tool   planning · scan repository structure
 *   04:11.7   out    found 14 files matching CodexAdapter*
 *   04:08.9   ok     ✓ patch applied  +18 -4
 */

export type LogEventKind = "sys" | "tool" | "out" | "ok" | "err";

const KIND_TO_TEXT_COLOR: Record<LogEventKind, string> = {
  sys: "text-log-sys",
  tool: "text-log-tool",
  out: "text-log-out",
  ok: "text-log-ok",
  err: "text-log-error",
};

interface Props {
  /** e.g. "04:12.1" — pre-formatted, monospace will be applied. */
  timestamp: string;
  kind: LogEventKind;
  /** Body text. Pass a string for default rendering; node for inline highlights. */
  children: React.ReactNode;
  className?: string;
}

export function LogRow({ timestamp, kind, children, className }: Props) {
  return (
    <div
      className={cn(
        "grid items-baseline gap-4 py-0.5 font-mono text-[12px] leading-relaxed",
        "grid-cols-[64px_44px_1fr]",
        className,
      )}
    >
      <span className="text-text-muted tabular-nums">{timestamp}</span>
      <span className={cn("uppercase tracking-wide font-semibold", KIND_TO_TEXT_COLOR[kind])}>
        {kind}
      </span>
      <span className={cn("text-foreground break-words", kind === "ok" && "text-status-done")}>
        {children}
      </span>
    </div>
  );
}
