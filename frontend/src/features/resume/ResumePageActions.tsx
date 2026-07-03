"use client";

import { RefreshCcw, Save } from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import type { Project } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  activeProjectIsListed: boolean;
  hasUnsavedChanges: boolean;
  loading: boolean;
  loadingProjects: boolean;
  projectId: string | null;
  projectSelectPlaceholder: string;
  projects: Project[];
  saving: boolean;
  importing: boolean;
  onProjectChange: (projectId: string | null) => void;
  onRefresh: () => void;
  onSave: () => void;
}

export function ResumePageActions({
  activeProjectIsListed,
  hasUnsavedChanges,
  loading,
  loadingProjects,
  projectId,
  projectSelectPlaceholder,
  projects,
  saving,
  importing,
  onProjectChange,
  onRefresh,
  onSave,
}: Props) {
  const { t } = useI18n();
  const actionInProgress = saving || importing;

  return (
    <div className="flex w-full max-w-full flex-wrap items-center justify-start gap-2 lg:w-auto lg:justify-end">
      <select
        value={projectId ?? ""}
        onChange={(event) => onProjectChange(event.target.value || null)}
        disabled={loadingProjects || projects.length === 0}
        className="h-11 min-w-0 flex-[1_1_220px] rounded-xl border border-border-subtle bg-surface-input px-3 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50 lg:min-w-[220px]"
        aria-label={t("resume.project")}
      >
        {!activeProjectIsListed && projectId && <option value={projectId}>{projectId}</option>}
        {projects.length === 0 && <option value="">{projectSelectPlaceholder}</option>}
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onRefresh}
        disabled={!projectId || loading || actionInProgress}
        className="inline-flex h-11 min-w-[76px] flex-none items-center justify-center gap-2 rounded-xl border border-border bg-surface px-3 text-sm font-medium transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        <RefreshCcw size={15} className={loading ? "animate-spin" : ""} />
        {t("resume.refresh")}
      </button>
      <button
        type="button"
        onClick={onSave}
        disabled={!projectId || saving || importing || !hasUnsavedChanges}
        className="inline-flex h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-brand px-4 text-sm font-semibold text-brand-foreground shadow-sm transition-colors hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
      >
        {saving ? <AgentThinkingIndicator phase="tool" size={15} /> : <Save size={15} />}
        {saving ? t("resume.saving") : t("resume.save")}
      </button>
    </div>
  );
}
