"use client";

import type { CodexTask, ExecutionProcess, RuntimeCatalog } from "@/lib/types";
import { Plus, Layout, Activity, Clock, Terminal, Trash2 } from "lucide-react";
import { useState, useEffect, useMemo, useCallback } from "react";
import { type Phase, PHASE_CONFIG } from "@/features/issues/phaseUtils";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";
import { pickLatestExecutionProcessForTask } from "@/lib/task-selection";
import { ExecutionConfigSelector, getFallbackConfig, type ExecutionConfigValue } from "@/components/runtime/ExecutionConfigSelector";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getRuntimeCatalog } from "@/lib/api";

function isDevelopmentTaskUnlocked(task: CodexTask, allTasks: CodexTask[]): boolean {
  if (task.phase !== "development" || task.sequence_index == null) return true;
  if (task.sequence_index === 0) return true;
  const prevIndex = task.sequence_index - 1;
  const prevTask = allTasks.find(
    (t) => t.phase === "development" && t.sequence_index === prevIndex && t.sequence_group === task.sequence_group
  );
  // Must be strictly "done" (approved), not "awaiting_review" or "rework"
  return prevTask?.status === "done";
}

interface TaskBoardProps {
  tasks: CodexTask[];
  executionProcesses: ExecutionProcess[];
  onSelectTask: (id: string) => void;
  onRunPhase: (phase: Phase, executor: "codex" | "claude", provider: string | null, model: string | null) => void;
  issueTitle?: string | null;
  onDeleteIssue?: () => Promise<void> | void;
}

export function TaskBoard({
  tasks,
  executionProcesses,
  onSelectTask,
  onRunPhase,
  issueTitle,
  onDeleteIssue,
}: TaskBoardProps) {
  const { t } = useI18n();
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  const defaultExecutionConfig = useMemo<ExecutionConfigValue>(() => getFallbackConfig(
    catalog,
    "codex",
    null,
    null,
  ), [catalog]);
  const [executionConfig, setExecutionConfig] = useState<ExecutionConfigValue>(defaultExecutionConfig);
  const [deleteIssueOpen, setDeleteIssueOpen] = useState(false);
  const [isDeletingIssue, setIsDeletingIssue] = useState(false);

  useEffect(() => {
    getRuntimeCatalog().then(setCatalog).catch(() => setCatalog(null));
  }, []);

  useEffect(() => {
    setExecutionConfig(defaultExecutionConfig);
  }, [defaultExecutionConfig]);

  const boardPhases: { id: Phase; labelKey: string; color: string }[] = [
    { id: "requirements", labelKey: "phase.requirements", color: "bg-text-muted" },
    { id: "architecture", labelKey: "phase.architecture", color: "bg-warning" },
    { id: "development", labelKey: "phase.development", color: "bg-brand" },
    { id: "testing", labelKey: "phase.testing", color: "bg-success" },
  ];

  const tasksByPhase = useMemo(() => boardPhases.reduce((acc, phase) => {
    let phaseTasks = tasks.filter((t) => t.phase === phase.id);
    if (phase.id === "development") {
      phaseTasks = phaseTasks
        .slice()
        .sort((a, b) => (a.sequence_index ?? 0) - (b.sequence_index ?? 0));
    }
    acc[phase.id] = phaseTasks;
    return acc;
  }, {} as Record<Phase, CodexTask[]>), [tasks]);

  const handleDeleteIssue = useCallback(async () => {
    if (!onDeleteIssue) return;
    setIsDeletingIssue(true);
    try {
      await onDeleteIssue();
      setDeleteIssueOpen(false);
    } finally {
      setIsDeletingIssue(false);
    }
  }, [onDeleteIssue]);

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      {/* Board Header */}
      <div className="flex items-center justify-between p-6 border-b border-border-subtle bg-surface/50">
        <div className="flex items-center gap-4">
          <div className="size-8 rounded-xl bg-surface-raised border border-border-subtle flex items-center justify-center shadow-sm">
            <Layout size={18} className="text-brand" />
          </div>
          <div>
            <h2 className="text-lg font-black tracking-tighter text-foreground">{t("task.boardTitle")}</h2>
            <p className="text-[10px] uppercase tracking-[0.2em] font-bold text-text-muted">{t("task.workflowExecution")}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div>
            <label className="block text-[10px] font-black uppercase tracking-[0.2em] text-text-muted mb-2">
              {t("task.executor")}
            </label>
            <ExecutionConfigSelector
              value={executionConfig}
              onChange={setExecutionConfig}
              catalog={catalog}
              className="w-full min-w-[36rem] lg:min-w-0"
            />
          </div>
          {onDeleteIssue && (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              className="self-end text-text-muted hover:text-error hover:bg-error/10"
              onClick={() => setDeleteIssueOpen(true)}
              title={t("issue.delete")}
              aria-label={t("issue.delete")}
            >
              <Trash2 size={14} />
            </Button>
          )}
        </div>
      </div>

      {/* Swimlanes */}
      <div className="flex-1 overflow-x-auto no-scrollbar bg-surface/5">
        <div className="flex h-full min-w-max p-6 gap-6">
          {boardPhases.map((phase) => {
            const phaseTasks = tasksByPhase[phase.id];
            return (
              <div key={phase.id} className="flex flex-col w-[350px] shrink-0 group/column">
                <div className="flex items-center justify-between mb-6 px-1">
                  <div className="flex items-center gap-3">
                    <div className={`size-2.5 rounded-full ${phase.color} shadow-sm`} />
                    <h3 className="text-[11px] font-black uppercase tracking-[0.25em] text-text-secondary group-hover/column:text-foreground transition-colors">
                      {t(phase.labelKey as any)}
                    </h3>
                    <span className="text-[10px] font-black text-text-muted bg-surface-raised px-2.5 py-0.5 rounded-full border border-border-subtle shadow-sm">
                      {phaseTasks.length}
                    </span>
                  </div>
                  <button
                    onClick={() => onRunPhase(phase.id, executionConfig.executor as "codex" | "claude", executionConfig.provider, executionConfig.model)}
                    className="p-1.5 rounded-lg hover:bg-surface-hover text-text-muted hover:text-brand transition-all opacity-0 group-hover/column:opacity-100"
                    title={t("issue.runPhase")}
                    aria-label={t("issue.runPhase")}
                  >
                    <Plus size={14} />
                  </button>
                </div>

                <div className="flex flex-col gap-4 flex-1 overflow-y-auto no-scrollbar pb-20">
                  {phaseTasks.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-20 opacity-[0.03] border-2 border-dashed border-foreground rounded-3xl">
                      <p className="text-[10px] uppercase tracking-widest font-black">{t("task.ready")}</p>
                    </div>
                  ) : (
                    phaseTasks.map((task) => {
                    const process = pickLatestExecutionProcessForTask(executionProcesses, task.id);
                    // Prioritize task status over process status for accuracy
                    const rawStatus = task.status || process?.status || "pending";
                    const status = rawStatus.toLowerCase();
                    const unlocked = isDevelopmentTaskUnlocked(task, tasks);

                    return (
                      <div
                        key={task.id}
                        onClick={() => onSelectTask(task.id)}
                        className={cn(
                          "group/card p-5 rounded-2xl bg-surface/40 border hover:bg-surface-hover hover:border-brand/30 hover:shadow-2xl hover:-translate-y-0.5 transition-all cursor-pointer animate-in fade-in slide-in-from-bottom-2 duration-500",
                          !unlocked && "opacity-60"
                        )}
                      >
                        <div className="flex items-start justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <div className={cn(
                              "size-1.5 rounded-full",
                              status === "running" || status === "responding" ? "bg-brand animate-pulse" :
                              status === "failed" ? "bg-error" :
                              status === "completed" || status === "done" ? "bg-success" :
                              status === "awaiting_review" ? "bg-warning animate-pulse" :
                              status === "rework" ? "bg-error shadow-[0_0_8px_rgba(239,68,68,0.4)]" :
                              "bg-text-muted"
                            )} />
                            <span className="text-[9px] font-black uppercase tracking-widest text-text-secondary group-hover/card:text-foreground">
                              {rawStatus}
                            </span>
                          </div>
                            <div className="flex items-center gap-2">
                              {task.phase === "development" && task.sequence_index != null && (
                                <span className={cn(
                                  "text-[9px] font-black px-1.5 py-0.5 rounded-md",
                                  unlocked ? "text-brand bg-brand/10" : "text-warning bg-warning/10"
                                )}>
                                  #{task.sequence_index + 1}
                                </span>
                              )}
                              {!unlocked && (
                                <span className="text-[9px] font-black text-warning bg-warning/10 px-1.5 py-0.5 rounded-md">
                                  {status === "rework" ? "REWORK REQUIRED" : t("task.sequence.blocked")}
                                </span>
                              )}
                              <div className="p-1.5 rounded-lg bg-surface-raised opacity-0 group-hover/card:opacity-100 transition-opacity">
                                <Terminal size={12} className="text-text-muted" />
                              </div>
                            </div>
                          </div>

                          <h4 className="text-[14px] font-bold text-foreground mb-4 line-clamp-2 leading-tight group-hover/card:text-brand transition-colors">
                            {task.title}
                          </h4>

                          <div className="flex items-center gap-4 text-[10px] font-bold text-text-muted">
                            <div className="flex items-center gap-1.5">
                              <Activity size={12} />
                              <span>{task.role.split('_').pop()?.toUpperCase()}</span>
                            </div>
                            <div className="flex items-center gap-1.5 ml-auto">
                              <Clock size={12} />
                              <span>{task.created_at ? new Date(task.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</span>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <Dialog open={deleteIssueOpen} onOpenChange={setDeleteIssueOpen}>
        <DialogContent className="sm:max-w-md" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("issue.delete")}</DialogTitle>
            <DialogDescription className="space-y-3">
              <p>{t("issue.deleteConfirmBody")}</p>
              {issueTitle && (
                <p className="text-foreground font-semibold">
                  {issueTitle}
                </p>
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="sm:justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteIssueOpen(false)}
              disabled={isDeletingIssue}
            >
              {t("issue.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDeleteIssue}
              disabled={isDeletingIssue}
            >
              {isDeletingIssue ? t("issue.deleting") : t("issue.deleteConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
