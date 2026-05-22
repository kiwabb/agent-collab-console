"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { CodexTask, ExecutionProcess, RuntimeCatalog } from "@/lib/types";
import { Plus, Layout, Activity, Clock, Terminal, Trash2, GripVertical, Link, Check, Table2, Kanban } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
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
import { useToast } from "@/components/ui/toast";

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return date.toLocaleDateString();
}

function formatDuration(startStr: string | null, endStr: string | null): string {
  if (!startStr) return "-";
  const start = new Date(startStr).getTime();
  const end = endStr ? new Date(endStr).getTime() : Date.now();
  const diffMs = end - start;
  if (diffMs < 0) return "-";
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour > 0) return `${diffHour}h ${diffMin % 60}m`;
  if (diffMin > 0) return `${diffMin}m ${diffSec % 60}s`;
  return `${diffSec}s`;
}

function isDevelopmentTaskUnlocked(task: CodexTask, allTasks: CodexTask[]): boolean {
  if (task.phase !== "development" || task.sequence_index == null) return true;
  if (task.sequence_index === 0) return true;
  const prevIndex = task.sequence_index - 1;
  const prevTask = allTasks.find(
    (t) => t.phase === "development" && t.sequence_index === prevIndex && t.sequence_group === task.sequence_group
  );
  return prevTask?.status === "done";
}

const BOARD_PHASES: { id: Phase; labelKey: string; color: string }[] = [
  { id: "requirements", labelKey: "phase.requirements", color: "bg-text-muted" },
  { id: "architecture", labelKey: "phase.architecture", color: "bg-warning" },
  { id: "development", labelKey: "phase.development", color: "bg-brand" },
  { id: "testing", labelKey: "phase.testing", color: "bg-success" },
];

interface TaskBoardProps {
  tasks: CodexTask[];
  executionProcesses: ExecutionProcess[];
  onSelectTask: (id: string) => void;
  onRunPhase: (phase: Phase, executor: "codex" | "claude", provider: string | null, model: string | null) => void;
  onReorderTasks?: (tasks: CodexTask[]) => void;
  issueTitle?: string | null;
  onDeleteIssue?: () => Promise<void> | void;
}

interface TaskCardProps {
  task: CodexTask;
  process: ExecutionProcess | undefined;
  unlocked: boolean;
  onClick: () => void;
  isDragging?: boolean;
}

function TaskCard({ task, process, unlocked, onClick, isDragging }: TaskCardProps) {
  const [copied, setCopied] = useState(false);
  const rawStatus = task.status || process?.status || "pending";
  const status = rawStatus.toLowerCase();

  const handleCopyLink = async (e: React.MouseEvent) => {
    e.stopPropagation();
    const url = `${window.location.origin}?workspace=${task.session_id}&issue=${task.issue_id}&task=${task.id}`;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <motion.div
      layout
      onClick={onClick}
      whileHover={{ y: -2, scale: 1.01, boxShadow: "0 10px 25px -5px rgba(0,0,0,0.1)" }}
      whileTap={{ scale: 0.98 }}
      className={cn(
        "group/card p-5 rounded-2xl bg-surface/40 border border-border-subtle hover:bg-surface-hover hover:border-brand/30 transition-all cursor-pointer",
        !unlocked && "opacity-60",
        isDragging && "shadow-2xl border-brand/50 bg-surface-raised rotate-2 z-50"
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
          <span className="text-[9px] font-black uppercase tracking-widest text-text-secondary group-hover/card:text-foreground transition-colors">
            {rawStatus}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCopyLink}
            className="p-1 rounded hover:bg-surface-hover text-text-muted hover:text-brand transition-all opacity-0 group-hover/card:opacity-100"
            title="Copy link"
          >
            {copied ? <Check size={12} className="text-success" /> : <Link size={12} />}
          </button>
          <div className="p-1 rounded bg-surface-raised opacity-0 group-hover/card:opacity-100 transition-opacity">
            <GripVertical size={12} className="text-text-muted cursor-grab" />
          </div>
          {task.phase === "development" && task.sequence_index != null && (
            <span className={cn(
              "text-[9px] font-black px-1.5 py-0.5 rounded-md transition-colors",
              unlocked ? "text-brand bg-brand/10" : "text-warning bg-warning/10"
            )}>
              #{task.sequence_index + 1}
            </span>
          )}
          {!unlocked && (
            <span className="text-[9px] font-black text-warning bg-warning/10 px-1.5 py-0.5 rounded-md">
              {status === "rework" ? "REWORK REQUIRED" : "BLOCKED"}
            </span>
          )}
        </div>
      </div>

      <h4 className="text-[14px] font-bold text-foreground mb-4 line-clamp-2 leading-tight group-hover/card:text-brand transition-colors">
        {task.title}
      </h4>

      <div className="flex items-center gap-4 text-[10px] font-bold text-text-muted">
        <div className="flex items-center gap-1.5 transition-colors group-hover/card:text-text-secondary">
          <Activity size={12} />
          <span>{task.role.split('_').pop()?.toUpperCase()}</span>
        </div>
        <div className="flex items-center gap-1.5 ml-auto transition-colors group-hover/card:text-text-secondary">
          <Clock size={12} />
          <span>{formatRelativeTime(task.created_at)}</span>
        </div>
      </div>
    </motion.div>
  );
}

interface SortableTaskCardProps {
  task: CodexTask;
  process: ExecutionProcess | undefined;
  unlocked: boolean;
  onClick: () => void;
}

function SortableTaskCard({ task, process, unlocked, onClick }: SortableTaskCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      <TaskCard
        task={task}
        process={process}
        unlocked={unlocked}
        onClick={onClick}
        isDragging={isDragging}
      />
    </div>
  );
}

export function TaskBoard({
  tasks,
  executionProcesses,
  onSelectTask,
  onRunPhase,
  onReorderTasks,
  issueTitle,
  onDeleteIssue,
}: TaskBoardProps) {
  const { t } = useI18n();
  const { addToast } = useToast();
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
  const [activeId, setActiveId] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"kanban" | "table">("kanban");

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  useEffect(() => {
    getRuntimeCatalog().then(setCatalog).catch(() => setCatalog(null));
  }, []);

  useEffect(() => {
    setExecutionConfig(defaultExecutionConfig);
  }, [defaultExecutionConfig]);

  const boardPhases = BOARD_PHASES;

  const tasksByPhase = useMemo(() => boardPhases.reduce((acc, phase) => {
    let phaseTasks = tasks.filter((t) => t.phase === phase.id);
    if (phase.id === "development") {
      phaseTasks = phaseTasks
        .slice()
        .sort((a, b) => (a.sequence_index ?? 0) - (b.sequence_index ?? 0));
    }
    acc[phase.id] = phaseTasks;
    return acc;
  }, {} as Record<Phase, CodexTask[]>), [boardPhases, tasks]);

  const handleDeleteIssue = useCallback(async () => {
    if (!onDeleteIssue) return;
    setIsDeletingIssue(true);
    try {
      await onDeleteIssue();
      addToast({ type: "success", title: "Issue deleted" });
      setDeleteIssueOpen(false);
    } catch (err) {
      addToast({
        type: "error",
        title: "Failed to delete issue",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setIsDeletingIssue(false);
    }
  }, [addToast, onDeleteIssue]);

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);

    if (!over || !onReorderTasks) return;

    if (active.id !== over.id) {
      const activeTask = tasks.find((t) => t.id === active.id);
      const overTask = tasks.find((t) => t.id === over.id);

      if (activeTask && overTask && activeTask.phase === overTask.phase) {
        const phaseTasks = tasksByPhase[activeTask.phase as Phase];
        const oldIndex = phaseTasks.findIndex((t) => t.id === active.id);
        const newIndex = phaseTasks.findIndex((t) => t.id === over.id);

        if (oldIndex !== -1 && newIndex !== -1) {
          const reordered = [...phaseTasks];
          const [removed] = reordered.splice(oldIndex, 1);
          reordered.splice(newIndex, 0, removed);

          const updatedTasks = tasks.map((task) => {
            const idx = reordered.findIndex((t) => t.id === task.id);
            if (idx !== -1 && task.phase === activeTask.phase) {
              return { ...task, sequence_index: idx };
            }
            return task;
          });
          onReorderTasks(updatedTasks);
        }
      }
    }
  };

  const activeTask = activeId ? tasks.find((t) => t.id === activeId) : null;

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
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
            <div className="flex items-end gap-1">
              <Button
                type="button"
                variant={viewMode === "kanban" ? "secondary" : "ghost"}
                size="icon-sm"
                onClick={() => setViewMode("kanban")}
                title="Kanban view"
                className={viewMode === "kanban" ? "bg-brand/10 text-brand" : "text-text-muted"}
              >
                <Kanban size={14} />
              </Button>
              <Button
                type="button"
                variant={viewMode === "table" ? "secondary" : "ghost"}
                size="icon-sm"
                onClick={() => setViewMode("table")}
                title="Table view"
                className={viewMode === "table" ? "bg-brand/10 text-brand" : "text-text-muted"}
              >
                <Table2 size={14} />
              </Button>
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
                        {t(phase.labelKey)}
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

                  <SortableContext
                    items={phaseTasks.map((t) => t.id)}
                    strategy={verticalListSortingStrategy}
                    id={phase.id}
                  >
                    <div className="flex flex-col gap-4 flex-1 overflow-y-auto no-scrollbar pb-20" data-tour="artifacts">
                      <AnimatePresence mode="popLayout">
                        {phaseTasks.length === 0 ? (
                          <motion.div 
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            className="flex flex-col items-center justify-center py-16 px-4 border-2 border-dashed border-border-subtle rounded-2xl bg-surface/10"
                          >
                            <div className="size-10 rounded-xl bg-surface-raised border border-border-subtle flex items-center justify-center mb-3 opacity-40">
                              <Plus size={16} className="text-text-muted" />
                            </div>
                            <p className="text-[10px] font-black uppercase tracking-widest text-text-muted/50">{t("task.ready")}</p>
                          </motion.div>
                        ) : (
                          phaseTasks.map((task, index) => {
                            const process = pickLatestExecutionProcessForTask(executionProcesses, task.id);
                            const unlocked = isDevelopmentTaskUnlocked(task, tasks);

                            return (
                              <motion.div
                                key={task.id}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, scale: 0.95 }}
                                transition={{ duration: 0.2, delay: index * 0.03 }}
                              >
                                <SortableTaskCard
                                  task={task}
                                  process={process ?? undefined}
                                  unlocked={unlocked}
                                  onClick={() => onSelectTask(task.id)}
                                />
                              </motion.div>
                            );
                          })
                        )}
                      </AnimatePresence>
                    </div>
                  </SortableContext>
                </div>
              );
            })}
          </div>
        </div>

        <DragOverlay>
          {activeTask && (
            <TaskCard
              task={activeTask}
              process={pickLatestExecutionProcessForTask(executionProcesses, activeTask.id) ?? undefined}
              unlocked={isDevelopmentTaskUnlocked(activeTask, tasks)}
              onClick={() => {}}
              isDragging
            />
          )}
        </DragOverlay>
      </DndContext>

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
