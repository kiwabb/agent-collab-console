"use client";

import { useEffect, useMemo, useState } from "react";
import { RotateCcw, Send, Sparkles, X, Terminal, MessageSquare, Code2, Zap } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { chatCodexTask, refineCodexTask, rerunCodexTask, terminateCodexTask } from "@/lib/api/tasks";
import { formatTok, formatCost, formatDuration } from "@/lib/format";
import { AgentLiveTimeline } from "@/features/runs/AgentLiveTimeline";
import { SubAgentResultCard } from "./SubAgentResultCard";
import { cn } from "@/lib/utils";
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

const STATUS_COLOR: Record<string, string> = {
  running: "var(--color-brand)",
  responding: "var(--color-brand)",
  pending: "var(--color-status-queued)",
  in_progress: "var(--color-brand)",
  done: "var(--color-status-done)",
  completed: "var(--color-status-done)",
  failed: "var(--color-status-failed)",
};

export function DispatchDrawer({ item, onClose }: Props) {
  const { addToast } = useToast();
  const { t } = useI18n();
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
  const isSchedulingDrawerMotion =
    item?.status === "running" && (item.kind === "dispatch" || item.kind === "tool");
  const drawerMotionPhase = item?.kind === "tool" ? "tool" : "dispatching";

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
      addToast({ type: "success", title: t("issue.command.drawer.actionDispatched", { action }) });
    } catch (err) {
      addToast({ type: "error", title: t("issue.command.drawer.actionFailed", { action }), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusyAction(null);
    }
  };

  const executionProcessId = item.task?.last_execution_process_id ?? null;
  const showLiveStream = item.kind === "dispatch" || item.kind === "tool";
  const statusColor = STATUS_COLOR[String(item.status).toLowerCase()] ?? "var(--color-text-muted)";
  const onStop =
    item.taskId && taskIsRunning
      ? async () => {
          try {
            await terminateCodexTask(item.taskId!);
            addToast({ type: "success", title: t("issue.command.drawer.stopRequested") });
          } catch (err) {
            addToast({
              type: "error",
              title: t("issue.command.drawer.stopFailed"),
              message: err instanceof Error ? err.message : String(err),
            });
          }
        }
      : undefined;

  const renderLiveStream = (heightClass: string) =>
    showLiveStream ? (
      <section className={`flex ${heightClass} shrink-0 flex-col rounded-2xl border border-border-subtle bg-surface-raised/60 overflow-hidden`}>
        <div className="px-4 py-3 flex items-center justify-between gap-3 border-b border-border-subtle bg-surface/60">
          <div className="flex items-center gap-2">
            <Terminal size={13} className="text-text-muted" />
            <h3 className="text-[11px] font-black uppercase tracking-[0.18em] text-text-muted">
              {t("issue.command.drawer.liveStream")}
            </h3>
          </div>
          <span className="font-mono text-[10px] text-text-faint bg-surface-input px-2 py-0.5 rounded-md">
            {executionProcessId ? executionProcessId.slice(0, 8) : t("issue.command.drawer.noRun")}
          </span>
        </div>
        <div className="flex-1 min-h-0 p-3">
          <AgentLiveTimeline
            executionProcessId={executionProcessId}
            taskStartedAt={item.task?.created_at ?? null}
            taskCompletedAt={item.task?.updated_at ?? null}
            taskStatus={taskStatusRaw}
            reviewComment={item.task?.review_comment ?? null}
            taskResult={item.task?.result ?? null}
            taskRole={item.task?.role ?? item.role ?? null}
            onStop={onStop}
            className="h-full"
            emptyHint={t("issue.command.drawer.waitingStart")}
          />
        </div>
      </section>
    ) : null;

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop with blur */}
      <button
        type="button"
        aria-label={t("issue.command.drawer.closeOverlay")}
        className="absolute inset-0 bg-black/40 backdrop-blur-[2px] transition-opacity"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <aside className="absolute right-0 top-0 flex h-full w-[680px] max-w-[calc(100vw-24px)] flex-col border-l border-border-subtle bg-background shadow-[0_0_80px_-20px_rgba(0,0,0,0.6)]">
        {/* ─── Premium Header ─── */}
        <div
          className={cn(
            "relative flex items-start justify-between gap-4 px-6 py-5 border-b border-border-subtle overflow-hidden transition-colors",
            isSchedulingDrawerMotion && "motion-essential border-brand/35",
          )}
          style={{
            background: `linear-gradient(135deg, color-mix(in srgb, ${statusColor} 8%, var(--color-surface)) 0%, var(--color-surface) 100%)`,
          }}
        >
          {isSchedulingDrawerMotion && (
            <span
              aria-hidden
              className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
            />
          )}
          {/* Subtle accent line */}
          <div
            className="absolute bottom-0 left-0 right-0 h-[2px]"
            style={{
              background: `linear-gradient(90deg, ${statusColor}, transparent 60%)`,
              opacity: 0.5,
            }}
          />

          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5 mb-2">
              {isSchedulingDrawerMotion && (
                <span className="inline-flex size-6 items-center justify-center rounded-lg border border-brand/30 bg-brand-muted/15 text-brand">
                  <AgentThinkingIndicator phase={drawerMotionPhase} size={13} />
                </span>
              )}
              <span
                className="inline-flex px-2 py-0.5 rounded-lg text-[10px] font-black uppercase tracking-[0.15em] border"
                style={{
                  color: statusColor,
                  borderColor: `color-mix(in srgb, ${statusColor} 30%, transparent)`,
                  backgroundColor: `color-mix(in srgb, ${statusColor} 8%, transparent)`,
                }}
              >
                {item.role}
              </span>
              <span
                className="inline-flex px-2 py-0.5 rounded-lg text-[10px] font-bold uppercase tracking-wide border"
                style={{
                  color: statusColor,
                  borderColor: `color-mix(in srgb, ${statusColor} 25%, transparent)`,
                  backgroundColor: `color-mix(in srgb, ${statusColor} 6%, transparent)`,
                }}
              >
                {item.status}
              </span>
            </div>
            {/* Execution meta row (executor, model, tokens, cost, duration) */}
            {(() => {
              const lastRun = item.task?.last_run;
              const executor = lastRun?.executor ?? item.task?.executor;
              const model = lastRun?.model ?? item.task?.model;
              const inputTokens = lastRun?.input_tokens;
              const outputTokens = lastRun?.output_tokens;
              const totalCost = lastRun?.total_cost_usd;
              const duration = lastRun?.duration_seconds;

              const parts: string[] = [];
              if (executor) parts.push(executor);
              if (model) parts.push(model);
              if (inputTokens != null || outputTokens != null) {
                const inp = inputTokens ?? 0;
                const out = outputTokens ?? 0;
                parts.push(`↑${formatTok(inp)} / ↓${formatTok(out)} tok`);
              }
              if (totalCost != null) parts.push(formatCost(totalCost));
              if (duration != null) parts.push(formatDuration(duration));

              return parts.length > 0 ? (
                <p className="mt-1 text-[10px] text-text-muted font-mono">
                  {parts.join(" · ")}
                </p>
              ) : null;
            })()}
            <h2 className="text-[16px] font-black text-foreground leading-snug tracking-tight line-clamp-2">
              {item.titleKey ? t(item.titleKey, item.titleParams) : item.title}
            </h2>
            <p className="mt-1.5 font-mono text-[11px] text-text-faint truncate">
              {item.taskId ?? item.toolUseId ?? item.id}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="rounded-xl shrink-0 mt-0.5 hover:bg-surface-hover"
          >
            <X size={16} />
          </Button>
        </div>

        {/* ─── Content area ─── */}
        {/* Block flow (not a flex column) on purpose: a flex column would shrink
            siblings to fit and crush the result card / actions to slivers while
            the fixed-height live stream kept its size. Block + space-y lets each
            child keep its natural height and the panel scroll normally. */}
        <div className="min-h-0 flex-1 space-y-5 px-6 py-5 overflow-y-auto overflow-x-hidden">
          {/* While the task is running, the live stream is the focus — show it
              first and tall so the user can watch it unfold. */}
          {taskIsRunning ? renderLiveStream("h-[clamp(300px,44vh,520px)]") : null}

          {/* Primary content. A finished task leads with its result (so the
              architecture / implementation summary is visible immediately); a
              running task shows a pending placeholder; the raw summary is the
              fallback only when no structured SubAgentResult was persisted. */}
          {taskIsRunning ? (
            <div
              data-density="dispatch-drawer-running"
              className={cn(
                "relative overflow-hidden rounded-2xl border p-5 flex items-center gap-3",
                "motion-essential border-brand/30 bg-brand-muted/10",
              )}
            >
              <span
                aria-hidden
                className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
              />
              <AgentThinkingIndicator phase={drawerMotionPhase} size={16} className="shrink-0" />
              <span className="text-[13px] italic text-text-muted">
                {t("issue.command.drawer.runningSummaryPending")}
              </span>
            </div>
          ) : item.result ? (
            <SubAgentResultCard result={item.result} />
          ) : item.summary ? (
            <section className="rounded-2xl border border-border-subtle bg-surface-raised/60 overflow-hidden">
              <div className="px-4 py-3 flex items-center gap-2 border-b border-border-subtle bg-surface/60">
                <MessageSquare size={13} className="text-text-muted" />
                <h3 className="text-[11px] font-black uppercase tracking-[0.18em] text-text-muted">
                  {t("issue.command.drawer.summary")}
                </h3>
              </div>
              <div className="px-4 py-4">
                <pre className="whitespace-pre-wrap text-[13px] leading-relaxed text-text-secondary font-sans">
                  {item.summary}
                </pre>
              </div>
            </section>
          ) : (
            <div className="rounded-2xl border border-border-subtle bg-surface-raised/60 p-5 text-[13px] text-text-muted text-center">
              {t("issue.command.drawer.noResult")}
            </div>
          )}

          {/* Once finished, the live stream is historical — keep it below the
              result and compact so the summary stays above the fold. */}
          {!taskIsRunning ? renderLiveStream("h-[clamp(220px,32vh,360px)]") : null}

          {/* Task Actions Section */}
          <section className="rounded-2xl border border-border-subtle bg-surface-raised/60 overflow-hidden">
            <div className="px-4 py-3 flex items-center justify-between gap-3 border-b border-border-subtle bg-surface/60">
              <div className="flex items-center gap-2">
                <Zap size={13} className="text-text-muted" />
                <h3 className="text-[11px] font-black uppercase tracking-[0.18em] text-text-muted">
                  {t("issue.command.drawer.taskActions")}
                </h3>
              </div>
              <span className="font-mono text-[10px] text-text-faint bg-surface-input px-2 py-0.5 rounded-md">
                {item.taskId ? item.taskId.slice(0, 8) : t("issue.command.drawer.noTask")}
              </span>
            </div>
            <div className="p-4">
              <textarea
                value={draft}
                disabled={!item.taskId || busyAction != null}
                onChange={(event) => setDraft(event.target.value)}
                rows={3}
                placeholder={
                  item.taskId
                    ? t("issue.command.drawer.actionPlaceholder")
                    : t("issue.command.drawer.noActionTarget")
                }
                className="w-full resize-none rounded-xl border border-border-subtle bg-background px-4 py-3 text-[13px] leading-relaxed outline-none placeholder:text-text-muted focus:border-brand/50 focus:ring-1 focus:ring-brand/20 transition-all"
              />
              <div className="mt-3.5 flex flex-wrap gap-2.5">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!item.taskId || !draft.trim() || busyAction != null}
                  onClick={() => void runTaskAction("chat")}
                  className="gap-2 rounded-xl px-4 hover:border-brand/40 hover:bg-brand/5 transition-all"
                >
                  {busyAction === "chat" ? (
                    <AgentThinkingIndicator phase="thinking" size={13} />
                  ) : (
                    <Send size={13} />
                  )}
                  {t("issue.command.drawer.chat")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!item.taskId || !draft.trim() || busyAction != null}
                  onClick={() => void runTaskAction("refine")}
                  className="gap-2 rounded-xl px-4 hover:border-brand/40 hover:bg-brand/5 transition-all"
                >
                  {busyAction === "refine" ? (
                    <AgentThinkingIndicator phase="thinking" size={13} />
                  ) : (
                    <Sparkles size={13} />
                  )}
                  {t("issue.command.drawer.refine")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!item.taskId || busyAction != null}
                  onClick={() => void runTaskAction("rerun")}
                  className="gap-2 rounded-xl px-4 hover:border-brand/40 hover:bg-brand/5 transition-all"
                >
                  {busyAction === "rerun" ? (
                    <AgentThinkingIndicator phase="dispatching" size={13} />
                  ) : (
                    <RotateCcw size={13} />
                  )}
                  {t("issue.command.drawer.rerun")}
                </Button>
              </div>
            </div>
          </section>

          {/* Raw Turns Section */}
          <section className="rounded-2xl border border-border-subtle bg-surface-raised/60 overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-2 border-b border-border-subtle bg-surface/60">
              <Code2 size={13} className="text-text-muted" />
              <h3 className="text-[11px] font-black uppercase tracking-[0.18em] text-text-muted">
                {t("issue.command.drawer.rawTurns")}
              </h3>
            </div>
            <div className="p-4">
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-text-secondary font-mono bg-background/50 rounded-xl border border-border-subtle p-3.5">
                {JSON.stringify(item.rawTurns, null, 2)}
              </pre>
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
