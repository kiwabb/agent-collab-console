"use client";

import { useState } from "react";
import type { CodexIssue, CodexTask, Artifact } from "@/lib/types";
import { PHASE_CONFIG, PHASES, type Phase } from "./phaseUtils";
import { Play, ChevronRight, Layout, ListTodo, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";
import type { TranslationKey } from "@/lib/i18n";

interface IssueDetailPanelProps {
  issue: CodexIssue | null;
  tasks: CodexTask[];
  artifacts: Artifact[];
  isRunning: boolean;
  onRunPhaseRole: (phase: string, role: string) => void;
  onChangePhase: (phase: string) => void;
}

export function IssueDetailPanel({
  issue,
  tasks,
  artifacts,
  isRunning,
  onRunPhaseRole,
  onChangePhase,
}: IssueDetailPanelProps) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<"tasks" | "artifacts">("tasks");

  if (!issue) {
    return (
      <div className="flex flex-col h-full items-center justify-center text-text-muted">
        <Layout size={48} strokeWidth={1} className="mb-4 opacity-10" />
        <p className="text-sm font-medium">{t("issue.selectEmpty")}</p>
      </div>
    );
  }

  const phase = issue.current_phase as Phase;
  const config = PHASE_CONFIG[phase] ?? PHASE_CONFIG.requirements;
  const issueTasks = tasks.filter((t) => t.issue_id === issue.id);

  const planArtifacts = artifacts.filter((a) => a.kind === "plan");
  const execArtifacts = artifacts.filter((a) => a.kind === "execution_result");
  const reqArtifacts = artifacts.filter((a) => a.name === "requirement.md" || a.name === "prd.json" || a.name === "prd.md");
  const shownArtifactNames = new Set([
    ...reqArtifacts.map((a) => a.name || a.id),
    ...planArtifacts.map((a) => a.name || a.id),
    ...execArtifacts.map((a) => a.name || a.id),
  ]);
  const otherArtifacts = artifacts.filter((a) => !shownArtifactNames.has(a.name || a.id));

  return (
    <div className="flex flex-col h-full bg-surface-raised/20 overflow-hidden">
      {/* Header Section */}
      <div className="p-6 border-b border-border-subtle bg-surface/40 backdrop-blur-md">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-bold tracking-tight text-foreground leading-snug">{issue.title}</h2>
            {issue.description && (
              <p className="mt-2 text-[12.5px] leading-relaxed text-text-secondary opacity-80">{issue.description}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 mb-6">
          <div className="flex items-center gap-1.5 bg-brand/10 px-2.5 py-0.5 rounded-full border border-brand/20">
            <div className="size-1.5 rounded-full bg-brand shadow-[0_0_8px_rgba(122,157,204,0.5)]" />
            <span className="text-[10px] font-black uppercase tracking-wider text-brand">
              {t(config.labelKey as TranslationKey)}
            </span>
          </div>
          <div className="h-3 w-px bg-white/5" />
          <span className="text-[10px] font-bold text-text-muted uppercase tracking-tight">
            {issueTasks.length} {issueTasks.length === 1 ? "Task" : "Tasks"}
          </span>
        </div>

        {/* Phase Selector Grid */}
        <div className="grid grid-cols-2 gap-1.5 p-1 bg-surface-input/50 rounded-xl border border-border-subtle">
          {PHASES.map((p) => {
            const c = PHASE_CONFIG[p];
            const isActive = p === phase;
            return (
              <button
                key={p}
                onClick={() => onChangePhase(p)}
                className={cn(
                  "px-2 py-2 text-[10px] font-bold uppercase tracking-[0.1em] rounded-lg transition-all duration-300",
                  isActive
                    ? "bg-brand text-background shadow-lg shadow-brand/10"
                    : "text-text-muted hover:text-foreground hover:bg-surface-hover"
                )}
              >
                {t(c.labelKey as any)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Tabs Section */}
      <div className="px-6 bg-surface/10 border-b border-border-subtle">
        <div className="flex gap-8">
          <button
            onClick={() => setActiveTab("tasks")}
            className={cn(
              "relative py-4 text-[10.5px] font-bold uppercase tracking-[0.15em] transition-all",
              activeTab === "tasks" ? "text-brand" : "text-text-muted hover:text-foreground"
            )}
          >
            {t("issue.tab.tasks")}
            {activeTab === "tasks" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand rounded-full" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("artifacts")}
            className={cn(
              "relative py-4 text-[10.5px] font-bold uppercase tracking-[0.15em] transition-all",
              activeTab === "artifacts" ? "text-brand" : "text-text-muted hover:text-foreground"
            )}
          >
            {t("issue.tab.artifacts")}
            {activeTab === "artifacts" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand rounded-full" />
            )}
          </button>
        </div>
      </div>

      {/* Content Section */}
      <div className="flex-1 overflow-y-auto p-6 no-scrollbar space-y-6">
        {activeTab === "tasks" ? (
          <div className="space-y-3">
            {issueTasks.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 opacity-20 border border-dashed border-border-strong rounded-2xl">
                <p className="text-[10px] uppercase tracking-widest font-black mb-6">{t("issue.noTasks")}</p>
                <button
                  onClick={() => onRunPhaseRole(phase, config.role)}
                  disabled={isRunning}
                  className="px-5 py-2 text-[10px] font-bold uppercase tracking-widest rounded-lg bg-surface-raised border border-border-subtle hover:bg-surface-hover transition-all"
                >
                  {t("issue.startPhase")}
                </button>
              </div>
            ) : (
              issueTasks.map((task) => (
                <div
                  key={task.id}
                  className="p-5 rounded-2xl border border-border-subtle bg-surface-raised/40 hover:border-border-strong hover:bg-surface-raised/60 transition-all group animate-in fade-in duration-500"
                >
                  <div className="flex items-center justify-between gap-4 mb-3">
                    <span className="text-[13.5px] font-bold tracking-tight text-foreground/90 truncate flex-1">{task.title}</span>
                    <StatusBadge status={task.status} />
                  </div>
                  <div className="flex items-center gap-2.5">
                    <span className="text-[10px] font-bold text-text-muted uppercase tracking-wider">{task.role}</span>
                    <div className="size-1 rounded-full bg-border-strong" />
                    <span className="text-[10px] font-bold text-text-muted uppercase tracking-wider">{task.executor}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        ) : (
          <div className="space-y-8 pb-10">
            {reqArtifacts.length > 0 && (
              <ArtifactSection title={t("issue.artifacts.requirements")} artifacts={reqArtifacts} icon={<FileText size={12} />} />
            )}
            {planArtifacts.length > 0 && (
              <ArtifactSection title={t("issue.artifacts.strategy")} artifacts={planArtifacts} icon={<ListTodo size={12} />} />
            )}
            {execArtifacts.length > 0 && (
              <ArtifactSection title={t("issue.artifacts.execution")} artifacts={execArtifacts} />
            )}
            {otherArtifacts.length > 0 && (
              <ArtifactSection title={t("artifacts.general")} artifacts={otherArtifacts} />
            )}
            {artifacts.length === 0 && (
              <div className="flex flex-col items-center justify-center py-20 opacity-20">
                <p className="text-[10px] uppercase tracking-widest font-black">{t("issue.artifacts.empty")}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer Action */}
      <div className="p-6 border-t border-border-subtle bg-surface/60 backdrop-blur-xl">
        <button
          onClick={() => onRunPhaseRole(phase, config.role)}
          disabled={isRunning}
          className="w-full flex items-center justify-center gap-3 px-6 py-4 text-xs font-bold uppercase tracking-[0.2em] rounded-xl bg-brand text-background hover:bg-brand/90 disabled:opacity-50 transition-all shadow-lg shadow-brand/20 group relative overflow-hidden"
        >
          {isRunning ? (
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 bg-background rounded-full animate-bounce [animation-delay:-0.3s]" />
              <div className="w-1.5 h-1.5 bg-background rounded-full animate-bounce [animation-delay:-0.15s]" />
              <div className="w-1.5 h-1.5 bg-background rounded-full animate-bounce" />
              <span className="ml-2">{t("run.executing")}</span>
            </div>
          ) : (
            <>
              <Play size={16} className="fill-current" />
              <span>{t(config.buttonLabelKey as any)}</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const isLive = s === "running" || s === "responding";
  
  const colors: Record<string, string> = {
    running: "bg-brand/10 text-brand border-brand/30",
    responding: "bg-brand/10 text-brand border-brand/30",
    completed: "bg-success/10 text-success border-success/30",
    failed: "bg-error/10 text-error border-error/30",
    waiting: "bg-warning/10 text-warning border-warning/30",
    blocked: "bg-error/10 text-error border-error/30",
    pending: "bg-surface-input text-text-muted border-border-subtle",
  };
  
  const cls = colors[s] ?? "bg-surface-input text-text-muted border-border-subtle";
  
  return (
    <div className={cn(
      "flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[9px] font-black uppercase tracking-wider",
      cls
    )}>
      {isLive && <div className="size-1 rounded-full bg-brand animate-pulse shadow-[0_0_5px_rgba(122,157,204,0.8)]" />}
      {status}
    </div>
  );
}

function ArtifactSection({ title, artifacts, icon }: { title: string; artifacts: Artifact[]; icon?: React.ReactNode }) {
  return (
    <div className="animate-in fade-in duration-500">
      <h4 className="flex items-center gap-2 text-[10px] font-black text-text-muted uppercase tracking-[0.2em] mb-4">
        {icon}
        {title}
      </h4>
      <div className="space-y-3">
        {artifacts.map((a) => (
          <div key={a.id} className="p-4 rounded-xl border border-border-subtle bg-surface/40 hover:bg-surface-hover hover:border-border-strong transition-all group cursor-pointer">
            <p className="text-[12px] font-bold text-foreground/80 mb-1.5 flex items-center justify-between">
              {a.name || a.kind}
              <ChevronRight size={14} className="opacity-0 group-hover:opacity-100 transition-all -translate-x-2 group-hover:translate-x-0 text-brand" />
            </p>
            <p className="text-[11px] leading-relaxed text-text-secondary opacity-60 line-clamp-2 font-medium">
              {typeof a.content === "string" ? a.content : JSON.stringify(a.content)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
