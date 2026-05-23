"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, RotateCcw, Send, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import {
  chatCodexTask,
  refineCodexTask,
  rerunCodexTask,
  terminateCodexTask,
} from "@/lib/api";
import { AgentLiveTimeline } from "@/features/runs/AgentLiveTimeline";
import { SubAgentResultCard } from "./SubAgentResultCard";
import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";

interface Props {
  item: DecisionTimelineItem | null;
  onClose: () => void;
}

const RUNNING_STATUSES = new Set([
  "running",
  "responding",
  "pending",
  "in_progress",
]);

export function DispatchDrawer({ item, onClose }: Props) {
  const { addToast } = useToast();
  const [draft, setDraft] = useState("");
  const [busyAction, setBusyAction] = useState<"chat" | "refine" | "rerun" | null>(null);

  useEffect(() => {
    if (!item) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, onClose]);

  const taskStatusRaw = item?.task?.status ?? null;
  const taskIsRunning = useMemo(() => {
    return RUNNING_STATUSES.has(String(taskStatusRaw || "").toLowerCase());
  }, [taskStatusRaw]);

  if (!item) return null;

  const runTaskAction = async (action: "chat" | "refine" | "rerun") => {
    if (!item.taskId) return;
    const content = draft.trim();
    if ((action === "chat" || action === "refine") && !content) return;
    setBusyAction(action);
    try {
      if (action === "chat") await chatCodexTask(item.taskId, content);
      if (action === "refine") await refineCodexTask(item.taskId, content);
      if (action === "rerun") await rerunCodexTask(item.taskId);
      if (action !== "rerun") setDraft("");
      addToast({ type: "success", title: `Task ${action} dispatched` });
    } catch (err) {
      addToast({ type: "error", title: `Task ${action} failed`, message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusyAction(null);
    }
  };

  const executionProcessId = item.task?.last_execution_process_id ?? null;
  const showLiveStream = item.kind === "dispatch" || item.kind === "tool";
  const onStop =
    item.taskId && taskIsRunning
      ? async () => {
          try {
            await terminateCodexTask(item.taskId!);
            addToast({ type: "success", title: "Task stop requested" });
          } catch (err) {
            addToast({
              type: "error",
              title: "Task stop failed",
              message: err instanceof Error ? err.message : String(err),
            });
          }
        }
      : undefined;

  return (
    <div className="fixed inset-0 z-50">
      <button
        type="button"
        aria-label="Close dispatch drawer overlay"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
      />
      <aside className="absolute right-0 top-0 flex h-full w-[560px] max-w-[calc(100vw-24px)] flex-col border-l border-border-subtle bg-background shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-5 py-4">
          <div className="min-w-0">
            <div className="font-mono text-xs font-bold uppercase text-brand">
              {item.role} · {item.status}
            </div>
            <h2 className="mt-1 truncate text-lg font-black text-foreground">{item.title}</h2>
            <p className="mt-1 font-mono text-xs text-text-muted">
              {item.taskId ?? item.toolUseId ?? item.id}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="rounded-xl">
            <X size={16} />
          </Button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-4 px-5 py-4">
          {showLiveStream ? (
            <section className="flex min-h-0 flex-[3] basis-[60%] flex-col rounded-2xl border border-border-subtle bg-surface-raised p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted">
                  Live stream
                </h3>
                <span className="font-mono text-[11px] text-text-muted">
                  {executionProcessId ? executionProcessId.slice(0, 8) : "no run"}
                </span>
              </div>
              <div className="flex-1 min-h-0">
                <AgentLiveTimeline
                  executionProcessId={executionProcessId}
                  taskStartedAt={item.task?.created_at ?? null}
                  taskStatus={taskStatusRaw}
                  reviewComment={item.task?.review_comment ?? null}
                  taskResult={item.task?.result ?? null}
                  taskRole={item.task?.role ?? item.role ?? null}
                  onStop={onStop}
                  className="h-full"
                  emptyHint="Waiting for task to start..."
                />
              </div>
            </section>
          ) : null}

          <div className="flex min-h-0 flex-[2] flex-col gap-4 overflow-auto">
            {taskIsRunning ? (
              <div className="rounded-2xl border border-border-subtle bg-surface-raised p-4 text-xs italic text-text-muted">
                Task is still running. Final summary will appear here once the task completes.
              </div>
            ) : item.result ? (
              <SubAgentResultCard result={item.result} />
            ) : (
              <div className="rounded-2xl border border-border-subtle bg-surface-raised p-4 text-sm text-text-muted">
                No SubAgentResult was persisted for this dispatch yet.
              </div>
            )}

            {item.summary && !taskIsRunning && (
              <section className="rounded-2xl border border-border-subtle bg-surface-raised p-4">
                <h3 className="mb-2 text-xs font-black uppercase tracking-[0.2em] text-text-muted">
                  Summary
                </h3>
                <pre className="whitespace-pre-wrap text-xs leading-relaxed text-text-secondary">
                  {item.summary}
                </pre>
              </section>
            )}

            <section className="rounded-2xl border border-border-subtle bg-surface-raised p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-xs font-black uppercase tracking-[0.2em] text-text-muted">
                  Task actions
                </h3>
                <span className="font-mono text-[11px] text-text-muted">
                  {item.taskId ? item.taskId.slice(0, 8) : "no task"}
                </span>
              </div>
              <textarea
                value={draft}
                disabled={!item.taskId || busyAction != null}
                onChange={(event) => setDraft(event.target.value)}
                rows={4}
                placeholder={
                  item.taskId
                    ? "Chat or refine this dispatched task..."
                    : "This timeline item has no task action target."
                }
                className="w-full resize-none rounded-xl border border-border-subtle bg-background px-3 py-2 text-xs outline-none placeholder:text-text-muted focus:border-brand/50"
              />
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!item.taskId || !draft.trim() || busyAction != null}
                  onClick={() => void runTaskAction("chat")}
                  className="gap-2 rounded-xl"
                >
                  {busyAction === "chat" ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Send size={13} />
                  )}
                  Chat
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!item.taskId || !draft.trim() || busyAction != null}
                  onClick={() => void runTaskAction("refine")}
                  className="gap-2 rounded-xl"
                >
                  {busyAction === "refine" ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <Sparkles size={13} />
                  )}
                  Refine
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!item.taskId || busyAction != null}
                  onClick={() => void runTaskAction("rerun")}
                  className="gap-2 rounded-xl"
                >
                  {busyAction === "rerun" ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    <RotateCcw size={13} />
                  )}
                  Rerun
                </Button>
              </div>
            </section>

            <section className="rounded-2xl border border-border-subtle bg-surface-raised p-4">
              <h3 className="mb-2 text-xs font-black uppercase tracking-[0.2em] text-text-muted">
                Raw conductor turns
              </h3>
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text-secondary">
                {JSON.stringify(item.rawTurns, null, 2)}
              </pre>
            </section>
          </div>
        </div>
      </aside>
    </div>
  );
}
