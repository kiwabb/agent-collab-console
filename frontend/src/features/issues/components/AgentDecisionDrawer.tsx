"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { getCodexTask } from "@/lib/api";
import type { CodexTask } from "@/lib/types";
import { cn } from "@/lib/utils";

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

  const sections = task ? extractSections(task) : [];

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-[480px] sm:w-[560px] flex flex-col">
        <SheetHeader className="px-5 pt-4 pb-2 shrink-0">
          <SheetTitle className="flex items-center gap-2 text-base">
            <span className="font-semibold">{task ? ROLE_LABEL[task.role ?? ""] ?? task.role : "Agent"} reasoning</span>
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
            <div className="flex items-center gap-2 text-sm text-text-muted py-6">
              <Loader2 size={14} className="animate-spin" />
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
              No structured reasoning to show. The agent may still be running
              or its output didn&apos;t parse as JSON. Check{" "}
              <a
                href={`/issues/${task.issue_id}?tab=tasks&taskId=${task.id}`}
                className="text-brand hover:underline"
              >
                Tasks · Runs
              </a>{" "}
              for raw logs.
            </div>
          )}
          {!loading && sections.map((s) => (
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

function extractSections(task: CodexTask): Array<
  { label: string; kind: "text"; value: string } | { label: string; kind: "list"; value: string[] }
> {
  if (!task.result) return [];
  let payload: Record<string, unknown> | null = null;
  try {
    payload = JSON.parse(task.result);
  } catch {
    // Not JSON — show as a single text block instead.
    return [{ label: "Result", kind: "text", value: task.result.slice(0, 2000) }];
  }
  const out: Array<
    { label: string; kind: "text"; value: string } | { label: string; kind: "list"; value: string[] }
  > = [];
  const text = (key: string, label: string) => {
    const v = payload?.[key];
    if (typeof v === "string" && v.trim()) out.push({ label, kind: "text", value: v });
  };
  const list = (key: string, label: string) => {
    const v = payload?.[key];
    if (Array.isArray(v) && v.length) {
      out.push({
        label,
        kind: "list",
        value: v.map((x) => (typeof x === "string" ? x : JSON.stringify(x))),
      });
    }
  };
  switch (task.role) {
    case "product_manager":
      text("requirement_analysis", "Requirement analysis");
      list("product_goals", "Product goals");
      list("user_stories", "User stories");
      list("acceptance_criteria", "Acceptance criteria");
      list("constraints", "Constraints");
      list("open_questions", "Open questions");
      list("risks", "Risks");
      break;
    case "architect":
      text("architecture_summary", "Architecture summary");
      list("components", "Components");
      list("data_models", "Data models");
      list("interfaces", "Interfaces");
      text("data_flow", "Data flow");
      list("risks", "Risks");
      list("open_questions", "Open questions");
      break;
    case "engineer":
      text("summary", "Summary");
      list("changed_files", "Changed files");
      list("verification_commands", "Verification commands");
      list("risks", "Risks");
      list("qa_notes", "QA notes");
      break;
    case "qa":
      text("final_recommendation", "Final recommendation");
      text("test_scope", "Test scope");
      list("acceptance_coverage", "Acceptance coverage");
      list("commands_run", "Commands run");
      list("bugs_found", "Bugs found");
      list("risks", "Risks");
      list("test_gaps", "Test gaps");
      break;
  }
  // Clarification question is universal.
  const q = (payload as Record<string, unknown>)?.clarification_question;
  if (typeof q === "string" && q.trim()) {
    out.unshift({ label: "Clarification question", kind: "text", value: q });
  }
  return out;
}
