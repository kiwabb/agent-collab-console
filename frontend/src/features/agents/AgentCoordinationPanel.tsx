"use client";

import type { CodexTask, HelpRequest, ExecutionProcess } from "@/lib/types";
import { HelpCircle, ArrowRight, Activity, Clock, Users } from "lucide-react";
import { getTaskRuntimeStatus, pickLatestExecutionProcessForTask } from "@/lib/task-selection";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface AgentCoordinationPanelProps {
  tasks: CodexTask[];
  helpRequests: HelpRequest[];
  executionProcesses: ExecutionProcess[];
  onSelectTask: (taskId: string) => void;
  onSelectProcess: (processId: string) => void;
}

export function AgentCoordinationPanel({
  tasks,
  helpRequests,
  executionProcesses,
  onSelectTask,
  onSelectProcess,
}: AgentCoordinationPanelProps) {
  const { t } = useI18n();
  const byRole: Record<string, CodexTask[]> = {};
  for (const task of tasks) {
    const role = task.role || "unknown";
    if (!byRole[role]) byRole[role] = [];
    byRole[role].push(task);
  }

  const activeProcesses = executionProcesses.filter(
    (p) => p.status === "running" || p.status === "responding",
  );
  const recentProcesses = [...executionProcesses].sort((a, b) => {
    const aTime = Math.max(
      Date.parse(a.created_at || "") || 0,
      Date.parse(a.started_at || "") || 0,
      Date.parse(a.updated_at || "") || 0,
      Date.parse(a.completed_at || "") || 0,
    );
    const bTime = Math.max(
      Date.parse(b.created_at || "") || 0,
      Date.parse(b.started_at || "") || 0,
      Date.parse(b.updated_at || "") || 0,
      Date.parse(b.completed_at || "") || 0,
    );
    return bTime - aTime;
  });

  return (
    <div className="flex flex-col h-full bg-background overflow-hidden">
      <div className="p-5 border-b border-border-subtle bg-surface/50">
        <h2 className="text-[10px] font-black uppercase tracking-[0.25em] text-text-muted">{t("agents.title")}</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-10 no-scrollbar pb-20">
        {activeProcesses.length > 0 && (
          <section className="animate-in fade-in duration-500">
            <h3 className="text-[10px] font-black text-brand uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
              <Activity size={12} className="text-brand" />
              {t("agents.active")}
            </h3>
            <div className="space-y-2.5">
              {activeProcesses.map((proc) => {
                const task = tasks.find((t) => t.id === proc.task_id);
                return (
                  <button
                    key={proc.id}
                    onClick={() => onSelectProcess(proc.id)}
                    className="w-full text-left p-4 rounded-2xl border border-brand/20 bg-brand/5 hover:bg-brand/10 transition-all group relative overflow-hidden"
                  >
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-brand" />
                    <span className="text-[13.5px] font-bold text-foreground/90 truncate block mb-1.5 transition-colors">
                      {task?.title || proc.task_id}
                    </span>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1.5">
                        <div className="size-1.5 rounded-full bg-brand animate-pulse shadow-[0_0_8px_rgba(122,157,204,0.5)]" />
                        <span className="text-[10px] font-black text-brand uppercase tracking-widest">{proc.status}</span>
                      </div>
                      <div className="h-3 w-px bg-brand/20" />
                      <span className="text-[10px] font-bold text-text-muted uppercase tracking-widest">{task?.executor || "codex"}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        <section>
          <h3 className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
            <Clock size={12} />
            {t("agents.recent")}
          </h3>
          <div className="space-y-1.5">
            {recentProcesses.length === 0 ? (
              <div className="py-12 flex flex-col items-center justify-center opacity-10">
                <p className="text-[10px] uppercase tracking-widest font-black">{t("agents.noHistory")}</p>
              </div>
            ) : (
              recentProcesses.slice(0, 5).map((proc) => {
                const task = tasks.find((t) => t.id === proc.task_id);
                const isCompleted = proc.status === "completed";
                const isFailed = proc.status === "failed";
                return (
                  <button
                    key={proc.id}
                    onClick={() => onSelectProcess(proc.id)}
                    className="w-full text-left p-3.5 rounded-xl border border-border-subtle bg-surface/30 hover:bg-surface-hover hover:border-border-strong transition-all group"
                  >
                    <span className="text-[12.5px] font-bold text-text-secondary truncate block mb-1.5 group-hover:text-foreground transition-colors">
                      {task?.title || proc.task_id}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-[9px] font-black uppercase tracking-widest",
                        isCompleted ? "text-success/80" : isFailed ? "text-error/80" : "text-text-muted/60"
                      )}>
                        {proc.status}
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <section>
          <h3 className="text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
            <Users size={12} />
            {t("agents.overview")}
          </h3>
          <div className="space-y-8">
            {Object.entries(byRole).map(([role, roleTasks]) => (
              <div key={role} className="animate-in fade-in duration-500">
                <div className="flex items-center justify-between mb-4 px-1">
                  <div className="flex items-center gap-2.5">
                    <div className="size-2 rounded-full bg-surface-input border border-border-strong" />
                    <span className="text-[10px] font-black text-text-muted uppercase tracking-[0.15em]">{role.replace("_", " ")}</span>
                  </div>
                  <span className="text-[10px] font-bold text-text-muted bg-surface-raised px-2 py-0.5 rounded-md border border-border-subtle">{roleTasks.length}</span>
                </div>
                <div className="space-y-1.5">
                  {roleTasks.map((task) => {
                    const latestProcess = pickLatestExecutionProcessForTask(executionProcesses, task.id);
                    const displayStatus = getTaskRuntimeStatus(task, executionProcesses);
                    const isTaskRunning = displayStatus === "running" || displayStatus === "responding";
                    
                    return (
                      <button
                        key={task.id}
                        onClick={() => {
                          if (latestProcess) {
                            onSelectProcess(latestProcess.id);
                          } else {
                            onSelectTask(task.id);
                          }
                        }}
                        className={cn(
                          "w-full text-left p-3 rounded-xl border transition-all",
                          isTaskRunning 
                            ? "border-brand/40 bg-brand/5" 
                            : "border-border-subtle bg-surface/20 hover:border-border-strong hover:bg-surface/40"
                        )}
                      >
                        <span className="text-[12.5px] font-bold text-text-secondary truncate block mb-1.5 tracking-tight group-hover:text-foreground">{task.title}</span>
                        <div className="flex items-center gap-2.5">
                          <div className={cn(
                            "size-1.5 rounded-full",
                            isTaskRunning ? "bg-brand animate-pulse shadow-[0_0_5px_rgba(122,157,204,0.6)]" : "bg-surface-input border border-border-strong"
                          )} />
                          <span className={cn(
                            "text-[9px] font-black uppercase tracking-widest",
                            isTaskRunning ? "text-brand" : "text-text-muted/60"
                          )}>
                            {displayStatus}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>

        {helpRequests.length > 0 && (
          <section className="animate-in fade-in duration-500">
            <h3 className="text-[10px] font-black text-warning uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
              <HelpCircle size={12} className="text-warning" />
              {t("agents.help")}
            </h3>
            <div className="space-y-3">
              {helpRequests.map((hr) => (
                <div
                  key={hr.id}
                  className="p-4 rounded-2xl border border-warning/30 bg-warning/5 relative overflow-hidden group hover:border-warning/50 transition-all"
                >
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-warning shadow-[0_0_8px_rgba(255,175,85,0.4)]" />
                  <div className="flex items-center justify-between gap-3 mb-3">
                    <span className="text-[12.5px] font-bold text-foreground/90 tracking-tight truncate">{hr.title || t("agents.helpNeeded")}</span>
                    <span className="px-2 py-0.5 rounded-md bg-warning/10 text-warning border border-warning/20 text-[9px] font-black uppercase tracking-widest">{hr.status}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2 px-2 py-1 rounded-md bg-warning/5 border border-warning/10">
                      <span className="text-[9px] font-black uppercase tracking-widest text-warning/70">{hr.source_executor}</span>
                    </div>
                    <ArrowRight size={12} className="text-warning/30" />
                    <div className="flex items-center gap-2 px-2 py-1 rounded-md bg-success/5 border border-success/10">
                      <span className="text-[9px] font-black uppercase tracking-widest text-success/70">{hr.target_executor}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
