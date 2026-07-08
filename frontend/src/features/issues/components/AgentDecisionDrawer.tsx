"use client";

import { useEffect, useState } from "react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { getCodexTask } from "@/lib/api/tasks";
import type { CodexTask } from "@/lib/types";
import { cn } from "@/lib/utils";
import { extractAgentResultSections } from "../issueResultParsing";

interface Props {
  taskId: string | null;
  open: boolean;
  onClose: () => void;
}

const ROLE_LABEL: Record<string, string> = {
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  qa: "QA",
};

/**
 * "Why did the agent decide this?" drawer. Pulls the structured JSON
 * result, surfaces the prose reasoning fields nicely (instead of dumping
 * the whole JSON), and links out to Tasks·Runs for the raw view.
 *
 * Devin shows a "chain of thought" sidebar; we don't have CoT but we have
 * the model's own structured prose (requirement_analysis,
 * architecture_summary, summary, final_recommendation) — distilled here.
 */
export function AgentDecisionDrawer({ taskId, open, onClose }: Props) {
  const [task, setTask] = useState<CodexTask | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !taskId) {
      setTask(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    void getCodexTask(taskId)
      .then((t) => {
        if (!cancelled) setTask(t);
      })
      .catch(() => {
        if (!cancelled) setTask(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, taskId]);

  const sections = task ? extractAgentResultSections(task.role ?? "", task.result ?? "") : [];

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[480px] sm:w-[560px] flex flex-col">
        <SheetHeader className="px-5 pt-4 pb-2 shrink-0">
          <SheetTitle className="flex items-center gap-2 text-base">
            <span className="font-semibold">
              {task ? (ROLE_LABEL[task.role ?? ""] ?? task.role) : "Agent"} reasoning
            </span>
            {task?.status && (
              <span
                className={cn(
                  "px-2 py-0.5 rounded text-[10px] uppercase tracking-wider",
                  task.status === "done"
                    ? "bg-status-done/15 text-status-done"
                    : task.status === "failed"
                      ? "bg-status-failed/15 text-status-failed"
                      : "bg-surface-input text-text-muted",
                )}
              >
                {task.status}
              </span>
            )}
          </SheetTitle>
          {task && (
            <SheetDescription className="text-xs text-text-muted">
              {task.title || task.id.slice(0, 8)}
            </SheetDescription>
          )}
        </SheetHeader>
        <div className="flex-1 overflow-auto px-5 pb-5 space-y-4">
          {loading && (
            <div
              data-density="agent-decision-loading"
              className="motion-essential relative flex items-center gap-2 overflow-hidden rounded-md border border-brand/25 bg-brand-muted/10 px-3 py-3 text-sm text-text-muted"
            >
              <span
                aria-hidden
                className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
              />
              <AgentThinkingIndicator phase="thinking" size={14} />
              Loading agent output…
            </div>
          )}
          {!loading && !task && (
            <div className="text-sm text-text-muted py-6 text-center">
              No agent output available yet.
            </div>
          )}
          {!loading && task && sections.length === 0 && (
            <div className="text-sm text-text-muted py-6">
              No structured reasoning to show. The agent may still be running or its output
              didn&apos;t parse as JSON. Check{" "}
              <a
                href={`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`}
                className="text-brand hover:underline"
              >
                Tasks · Runs
              </a>{" "}
              for raw logs.
            </div>
          )}
          {!loading &&
            sections.map((s) => (
              <section key={s.label}>
                <div className="text-[10px] font-black uppercase tracking-widest text-text-muted mb-1.5">
                  {s.label}
                </div>
                {s.kind === "text" ? (
                  <p className="text-[13px] leading-relaxed text-foreground/90 whitespace-pre-wrap">
                    {s.value}
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {s.value.map((v, i) => (
                      <li
                        key={i}
                        className="text-[13px] leading-relaxed text-foreground/90 flex gap-2"
                      >
                        <span className="text-text-muted">·</span>
                        <span>{v}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          {!loading && task && (
            <a
              href={`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`}
              className="block mt-6 text-[11px] text-text-muted hover:text-foreground"
            >
              Open raw run logs →
            </a>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
