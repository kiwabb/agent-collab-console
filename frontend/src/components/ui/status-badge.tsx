"use client";

import { cn } from "@/lib/utils";

/**
 * Dot+label pill matching the Console v2 reference style:
 *   • Done   • Running   • Awaiting approval   • Queued   • Failed
 *
 * The dot pulses when status is "running" / "awaiting".
 */

export type StatusKind = "done" | "running" | "awaiting" | "queued" | "failed" | "info";

const KIND_TO_TOKEN: Record<StatusKind, { dot: string; text: string; bg?: string }> = {
  done: { dot: "bg-status-done", text: "text-status-done" },
  running: { dot: "bg-status-running", text: "text-status-running" },
  awaiting: { dot: "bg-status-awaiting", text: "text-status-awaiting" },
  queued: { dot: "bg-status-queued", text: "text-text-muted" },
  failed: { dot: "bg-status-failed", text: "text-status-failed" },
  info: { dot: "bg-status-info", text: "text-status-info" },
};

interface Props {
  kind: StatusKind;
  label: string;
  /** Pulse the dot (default true for running / awaiting). */
  pulse?: boolean;
  className?: string;
}

export function StatusBadge({ kind, label, pulse, className }: Props) {
  const t = KIND_TO_TOKEN[kind];
  const shouldPulse = pulse ?? (kind === "running" || kind === "awaiting");
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium whitespace-nowrap",
        t.text,
        className,
      )}
    >
      <span className="relative inline-flex">
        <span className={cn("size-1.5 rounded-full", t.dot)} />
        {shouldPulse && (
          <span className={cn("absolute inset-0 rounded-full animate-ping opacity-60", t.dot)} />
        )}
      </span>
      {label}
    </span>
  );
}

/** Map any free-form status string to a StatusKind for the badge. */
export function inferStatusKind(raw: string | null | undefined): StatusKind {
  if (!raw) return "queued";
  const s = raw.toLowerCase();
  if (s.includes("done") || s === "completed" || s === "success") return "done";
  if (s === "running" || s.includes("in_progress") || s === "active") return "running";
  if (s.includes("await") || s.includes("approval") || s === "ready") return "awaiting";
  if (s === "failed" || s.includes("error") || s === "cancelled") return "failed";
  if (s === "queued" || s === "pending" || s === "blocked") return "queued";
  return "info";
}
