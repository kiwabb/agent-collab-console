"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { createWorkspace, getWorkspaces } from "@/lib/api/workspaces";
import { getProject, getProjectBranches, getProjectStats } from "@/lib/api/projects";
import type { GitBranch, Project, ProjectStats, Workspace } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Plus, FolderGit2, GitBranch as GitBranchIcon } from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useToast } from "@/components/ui/toast";
import { emitDataEvent } from "@/lib/dataEvents";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  projectId: string;
}

export function ProjectDashboard({ projectId }: Props) {
  const router = useRouter();
  const { addToast } = useToast();
  const { t } = useI18n();
  const [project, setProject] = useState<Project | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [branches, setBranches] = useState<GitBranch[]>([]);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  const load = useCallback(async () => {
    try {
      const [p, ws, s, b] = await Promise.all([
        getProject(projectId),
        getWorkspaces(projectId),
        getProjectStats(projectId).catch(() => null),
        getProjectBranches(projectId).catch(() => []),
      ]);
      setProject(p);
      setWorkspaces(ws);
      setStats(s);
      setBranches(b);
    } catch (err) {
      addToast({ type: "error", title: t("project.dashboard.loadFailed"), message: err instanceof Error ? err.message : String(err) });
    }
  }, [projectId, addToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = useCallback(async () => {
    const title = newTitle.trim();
    if (!title) return;
    try {
      const ws = await createWorkspace(title, projectId);
      setNewTitle("");
      setCreating(false);
      emitDataEvent("workspaces:changed");
      addToast({ type: "success", title: t("project.dashboard.workspaceCreated") });
      router.push(`/workspaces/${ws.id}`);
    } catch (err) {
      addToast({ type: "error", title: t("project.dashboard.workspaceCreateFailed"), message: err instanceof Error ? err.message : String(err) });
    }
  }, [newTitle, projectId, router, addToast, t]);

  if (!project) {
    return (
      <div
        data-density="project-dashboard-thinking-loading"
        className="motion-essential relative mx-auto flex min-h-[360px] max-w-6xl items-center justify-center gap-2 overflow-hidden px-8 py-6 text-sm font-semibold text-text-muted"
      >
        <span
          aria-hidden
          className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
        />
        <AgentThinkingIndicator phase="thinking" size={16} />
        {t("project.dashboard.loading")}
      </div>
    );
  }


  return (
    <div className="px-8 py-6 max-w-6xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 text-text-muted text-xs mb-1">
            <FolderGit2 size={14} />
            <span>{t("project.dashboard.project")}</span>
          </div>
          <h1 className="text-2xl font-black tracking-tight">{project.name}</h1>
          <p className="font-mono text-xs text-text-muted mt-1">{project.repo_path}</p>
        </div>
        <Button onClick={() => setCreating((v) => !v)}>
          <Plus size={14} className="mr-1" /> {t("project.dashboard.newWorkspace")}
        </Button>
      </div>

      {creating && (
        <div className="mb-6 flex gap-2 p-4 rounded-lg bg-surface-raised border border-border-subtle">
          <input
            autoFocus
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder={t("project.dashboard.workspaceTitlePlaceholder")}
            className="flex-1 bg-surface-input border border-border-subtle rounded-md px-3 py-2 text-sm outline-none focus:border-brand"
            onKeyDown={(e) => {
              if (e.key === "Enter") void handleCreate();
            }}
          />
          <Button onClick={() => void handleCreate()} disabled={!newTitle.trim()}>
            {t("project.dashboard.create")}
          </Button>
          <Button variant="outline" onClick={() => { setCreating(false); setNewTitle(""); }}>
            {t("project.dashboard.cancel")}
          </Button>
        </div>
      )}

      <section className="mb-6">
        <h2 className="text-xs font-black uppercase tracking-widest text-text-muted mb-3">{t("project.dashboard.workspaces")}</h2>
        {workspaces.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border-subtle p-8 text-center text-sm text-text-muted">
            {t("project.dashboard.noWorkspaces")}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {workspaces.map((ws) => (
              <button
                key={ws.id}
                type="button"
                onClick={() => router.push(`/workspaces/${ws.id}`)}
                className="text-left p-4 rounded-lg border border-border-subtle hover:border-border-strong hover:bg-surface-hover transition-colors"
              >
                <div className="font-semibold truncate">{ws.title || ws.id.slice(0, 8)}</div>
                <div className="text-[11px] text-text-muted mt-1 truncate">{ws.cwd}</div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {stats && (
          <div className="rounded-lg border border-border-subtle p-4">
            <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-2">{t("project.dashboard.issues")}</h3>
            <div className="grid grid-cols-4 gap-3 text-center">
              <Stat label={t("project.dashboard.total")} value={stats.issues_total ?? 0} />
              <Stat label={t("project.dashboard.open")} value={stats.issues_open ?? 0} />
              <Stat label={t("project.dashboard.merged")} value={stats.issues_merged ?? 0} />
              <Stat label={t("project.dashboard.abandoned")} value={stats.issues_abandoned ?? 0} />
            </div>
          </div>
        )}
        <div className="rounded-lg border border-border-subtle p-4">
          <h3 className="text-xs font-black uppercase tracking-widest text-text-muted mb-2 flex items-center gap-2">
            <GitBranchIcon size={12} /> {t("project.dashboard.branches")}
          </h3>
          {branches.length === 0 ? (
            <div className="text-sm text-text-muted">{t("project.dashboard.noBranches")}</div>
          ) : (
            <ul className="space-y-1 text-sm">
              {branches.slice(0, 8).map((b) => (
                <li key={b.name} className="flex justify-between items-center">
                  <span className="font-mono text-xs">{b.name}</span>
                  {b.is_current && <span className="text-[10px] font-bold text-brand">{t("project.dashboard.current")}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-2xl font-black">{value}</div>
      <div className="text-[10px] uppercase tracking-widest text-text-muted">{label}</div>
    </div>
  );
}
