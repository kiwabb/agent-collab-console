"use client";

import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { CodexTask, ExecutionProcess } from "@/lib/types";
import type { Phase } from "@/features/issues/phaseUtils";
import { Activity, Clock, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";
import { pickLatestExecutionProcessForTask } from "@/lib/task-selection";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";

interface TaskListProps {
  tasks: CodexTask[];
  allTasks: CodexTask[];
  executionProcesses: ExecutionProcess[];
  onSelectTask: (id: string) => void;
  phase: Phase;
}

function isDevelopmentTaskUnlocked(task: CodexTask, allTasks: CodexTask[]): boolean {
  if (task.phase !== "development" || task.sequence_index == null) return true;
  if (task.sequence_index === 0) return true;
  const prevIndex = task.sequence_index - 1;
  const prevTask = allTasks.find(
    (t) =>
      t.phase === "development" &&
      t.sequence_index === prevIndex &&
      t.sequence_group === task.sequence_group,
  );
  return prevTask?.status === "done";
}

export function VirtualizedTaskList({
  tasks,
  allTasks,
  executionProcesses,
  onSelectTask,
}: TaskListProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  // TanStack Virtual intentionally returns imperative helpers; React Compiler cannot memoize it safely.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: tasks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 140,
    overscan: 3,
  });

  const items = virtualizer.getVirtualItems();

  return (
    <div
      ref={parentRef}
      className="flex-1 overflow-y-auto no-scrollbar"
      style={{ contain: "strict" }}
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: "100%",
          position: "relative",
        }}
      >
        {items.map((virtualRow) => {
          const task = tasks[virtualRow.index];
          if (!task) return null;
          const process = pickLatestExecutionProcessForTask(executionProcesses, task.id);
          const rawStatus = task.status || process?.status || "pending";
          const status = rawStatus.toLowerCase();
          const isTaskActive = status === "running" || status === "responding";
          const unlocked = isDevelopmentTaskUnlocked(task, allTasks);

          return (
            <div
              key={task.id}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
              }}
              onClick={() => onSelectTask(task.id)}
              className={cn(
                "group/card p-5 rounded-2xl bg-surface/40 border hover:bg-surface-hover hover:border-brand/30 hover:shadow-2xl hover:-translate-y-0.5 transition-all cursor-pointer animate-in fade-in duration-500",
                !unlocked && "opacity-60",
              )}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  {isTaskActive ? (
                    <div
                      data-density="virtualized-task-active-status"
                      className="motion-essential flex size-3 items-center justify-center rounded-full"
                    >
                      <AgentThinkingIndicator phase="dispatching" size={10} />
                    </div>
                  ) : (
                    <div
                      className={cn(
                        "size-1.5 rounded-full",
                        status === "failed"
                          ? "bg-error"
                          : status === "completed" || status === "done"
                            ? "bg-success"
                            : status === "awaiting_review"
                              ? "bg-warning animate-pulse"
                              : status === "rework"
                                ? "bg-error shadow-[0_0_8px_rgba(239,68,68,0.4)]"
                                : "bg-text-muted",
                      )}
                    />
                  )}
                  <span className="text-[9px] font-black uppercase tracking-widest text-text-secondary group-hover/card:text-foreground">
                    {rawStatus}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {task.phase === "development" && task.sequence_index != null && (
                    <span
                      className={cn(
                        "text-[9px] font-black px-1.5 py-0.5 rounded-md",
                        unlocked ? "text-brand bg-brand/10" : "text-warning bg-warning/10",
                      )}
                    >
                      #{task.sequence_index + 1}
                    </span>
                  )}
                  {!unlocked && (
                    <span className="text-[9px] font-black text-warning bg-warning/10 px-1.5 py-0.5 rounded-md">
                      {status === "rework" ? "REWORK REQUIRED" : "BLOCKED"}
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
                  <span>{task.role.split("_").pop()?.toUpperCase()}</span>
                </div>
                <div className="flex items-center gap-1.5 ml-auto">
                  <Clock size={12} />
                  <span>
                    {task.created_at
                      ? new Date(task.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : ""}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
