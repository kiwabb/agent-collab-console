"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, ChevronDown, ChevronLeft, DownloadCloud, GitBranch as GitBranchIcon, Plus, RefreshCw, Trash2, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Skeleton } from "@/components/ui/skeleton";
import { InteractionEmptyState } from "@/components/ui/interaction-empty-state";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { deleteProject, getProjectAudit, getProjectBranches, getProjectRemoteStatus, getProjectStats, listProjects, pullProject, repairProject, updateProject } from "@/lib/api";
import { emitDataEvent } from "@/lib/dataEvents";
import type { ProjectAuditEntry, ProjectRemoteStatus, ProjectStats } from "@/lib/types";
import { Textarea } from "@/components/ui/textarea";
import type { GitBranch, Project } from "@/lib/types";
import { PageFrame } from "@/features/workbench/components/PageFrame";

import { CreateProjectDialog } from "./CreateProjectDialog";
import { BranchListView } from "./BranchListView";
import { STATS_LABELS } from "./statsLabels";
import { RemoteUpdateBadge } from "./RemoteUpdateBadge";
import { describePullResult } from "./projectRemoteStatus";

// How often to silently re-check the selected project against its remote.
const REMOTE_POLL_MS = 5 * 60_000;

function SetupScriptCard({
  project,
  onUpdated,
}: {
  project: Project;
  onUpdated: (next: Project) => void;
}) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [draft, setDraft] = useState(project.setup_script ?? "");
  const [saving, setSaving] = useState(false);
  // Setup script is an advanced/occasional field — collapse it by default.
  const [open, setOpen] = useState(false);
  // Reset the draft when the user switches between projects.
  useEffect(() => {
    setDraft(project.setup_script ?? "");
  }, [project.id, project.setup_script]);
  const dirty = draft !== (project.setup_script ?? "");

  async function save() {
    if (saving || !dirty) return;
    setSaving(true);
    try {
      const next = await updateProject(project.id, { setup_script: draft });
      onUpdated(next);
      addToast({ type: "success", title: t("projects.setupSaved") });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save setup script";
      addToast({ type: "error", title: msg });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="enterprise-card rounded-2xl overflow-hidden">
      <CardHeader>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center justify-between gap-2 text-left"
          aria-expanded={open}
        >
          <CardTitle className="text-base">{t("projects.setupScript")}</CardTitle>
          <ChevronDown
            size={16}
            className={cn("shrink-0 text-muted-foreground transition-transform", !open && "-rotate-90")}
          />
        </button>
        {open && <CardDescription className="mt-1">{t("projects.setupScriptHelp")}</CardDescription>}
      </CardHeader>
      {open && (
        <CardContent className="space-y-2">
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={t("projects.setupScriptPlaceholder")}
            rows={4}
            className="font-mono text-xs"
          />
          <div className="flex justify-end">
            <Button size="sm" onClick={save} disabled={!dirty || saving}>
              {saving ? t("projects.savingSetup") : t("projects.saveSetup")}
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

function RunCommandCard({
  project,
  onUpdated,
}: {
  project: Project;
  onUpdated: (next: Project) => void;
}) {
  const { t } = useI18n();
  const { addToast } = useToast();
  const [draft, setDraft] = useState(project.run_command ?? "");
  const [saving, setSaving] = useState(false);
  // Reset the draft when the user switches between projects.
  useEffect(() => {
    setDraft(project.run_command ?? "");
  }, [project.id, project.run_command]);
  const dirty = draft !== (project.run_command ?? "");

  async function save() {
    if (saving || !dirty) return;
    setSaving(true);
    try {
      const next = await updateProject(project.id, { run_command: draft });
      onUpdated(next);
      addToast({ type: "success", title: t("projects.runCommandSaved") });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save run command";
      addToast({ type: "error", title: msg });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="enterprise-card rounded-2xl overflow-hidden">
      <CardHeader>
        <CardTitle className="text-base">{t("projects.runCommandLabel")}</CardTitle>
        <CardDescription>{t("projects.runCommandHelp")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("projects.runCommandPlaceholder")}
          rows={3}
          className="font-mono text-xs"
        />
        <div className="flex justify-end">
          <Button size="sm" onClick={save} disabled={!dirty || saving}>
            {saving ? t("projects.savingSetup") : t("projects.saveSetup")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

const SELECTED_PROJECT_KEY = "selectedProjectId";

function formatRelative(iso: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  return `${Math.floor(hr / 24)}d`;
}

export function selectedProjectId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SELECTED_PROJECT_KEY);
}

export function setSelectedProjectId(id: string | null) {
  if (typeof window === "undefined") return;
  if (id) window.localStorage.setItem(SELECTED_PROJECT_KEY, id);
  else window.localStorage.removeItem(SELECTED_PROJECT_KEY);
}

export function ProjectsPage() {
  const router = useRouter();
  const { t } = useI18n();
  const { addToast } = useToast();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [branches, setBranches] = useState<GitBranch[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchesOpen, setBranchesOpen] = useState(true);
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [audit, setAudit] = useState<ProjectAuditEntry[]>([]);
  // Remote-update detection for the selected project. `null` status = not yet
  // loaded → the badge shows "checking…".
  const [remoteStatus, setRemoteStatus] = useState<ProjectRemoteStatus | null>(null);
  const [remoteChecking, setRemoteChecking] = useState(false);
  const [syncing, setSyncing] = useState(false);
  // Tick state: bumps every 60s so the "5m ago" labels stay reasonably fresh
  // without re-fetching the audit log. Used implicitly by formatRelative since
  // each render recomputes against Date.now().
  const [, setNowTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setNowTick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, []);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null);
  // When a normal delete reports "N workspace(s) attached", we surface a
  // second confirm asking permission to cascade. Holds the project id and
  // the backend message so the user sees the full context.
  const [cascadePending, setCascadePending] = useState<{
    project: Project;
    detail: string;
  } | null>(null);
  const [deletingProject, setDeletingProject] = useState(false);

  const activeProject = useMemo(
    () => projects?.find((p) => p.id === activeId) ?? null,
    [projects, activeId],
  );

  const visibleProjects = useMemo(() => {
    if (!projects) return null;
    const q = searchQuery.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) => p.name.toLowerCase().includes(q) || p.repo_path.toLowerCase().includes(q),
    );
  }, [projects, searchQuery]);

  const refresh = useCallback(async () => {
    try {
      const list = await listProjects();
      setProjects(list);
      const persisted = selectedProjectId();
      if (persisted && list.some((p) => p.id === persisted)) {
        setActiveId(persisted);
      } else if (list.length > 0) {
        setActiveId(list[0].id);
      } else {
        setActiveId(null);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load projects";
      addToast({ type: "error", title: msg });
      setProjects([]);
    }
  }, [addToast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!activeId) {
      setBranches([]);
      setStats(null);
      return;
    }
    let cancelled = false;
    setBranchesLoading(true);
    Promise.all([getProjectBranches(activeId), getProjectStats(activeId), getProjectAudit(activeId, 10)])
      .then(([brs, st, au]) => {
        if (cancelled) return;
        setBranches(brs);
        setStats(st);
        setAudit(au);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Failed to load project detail";
          addToast({ type: "error", title: msg });
          setBranches([]);
          setStats(null);
          setAudit([]);
        }
      })
      .finally(() => {
        if (!cancelled) setBranchesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, addToast]);

  // Fetch the selected project's remote status: immediately on selection (with
  // a real `git fetch`), then poll on an interval. Only the visible project is
  // checked, to keep network/process cost bounded.
  const loadRemoteStatus = useCallback(
    async (projectId: string, opts: { fetch: boolean }) => {
      setRemoteChecking(true);
      try {
        const status = await getProjectRemoteStatus(projectId, { fetch: opts.fetch });
        return status;
      } finally {
        setRemoteChecking(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!activeId) {
      setRemoteStatus(null);
      return;
    }
    let cancelled = false;
    const projectId = activeId;
    setRemoteStatus(null);
    const run = async () => {
      try {
        const status = await loadRemoteStatus(projectId, { fetch: true });
        if (!cancelled) setRemoteStatus(status);
      } catch {
        // Network/transient error — leave the badge in its checking state; the
        // next poll (or a manual "check for updates") will retry.
      }
    };
    void run();
    const id = setInterval(run, REMOTE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [activeId, loadRemoteStatus]);

  const handleCheckUpdate = useCallback(async () => {
    if (!activeProject) return;
    try {
      const status = await loadRemoteStatus(activeProject.id, { fetch: true });
      setRemoteStatus(status);
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("projects.syncFailedOffline");
      addToast({ type: "error", title: msg });
    }
  }, [activeProject, addToast, loadRemoteStatus, t]);

  const handleSync = useCallback(async () => {
    if (!activeProject || syncing) return;
    setSyncing(true);
    try {
      const result = await pullProject(activeProject.id);
      const toast = describePullResult(result, t);
      addToast({ type: toast.type, title: toast.title });
      // Refresh status + branches so the UI reflects the new HEAD.
      const status = await loadRemoteStatus(activeProject.id, { fetch: false });
      setRemoteStatus(status);
      if (result.success) {
        try {
          setBranches(await getProjectBranches(activeProject.id));
        } catch {
          // Branch list refresh is best-effort; the sync itself already landed.
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : t("projects.syncFailed");
      addToast({ type: "error", title: msg });
    } finally {
      setSyncing(false);
    }
  }, [activeProject, addToast, loadRemoteStatus, syncing, t]);

  const performDelete = useCallback(
    async (project: Project, force: boolean) => {
      setDeletingProject(true);
      try {
        await deleteProject(project.id, force);
        emitDataEvent("projects:changed");
        emitDataEvent("workspaces:changed");
        addToast({ type: "success", title: t("projects.toastDeleted") });
        if (selectedProjectId() === project.id) setSelectedProjectId(null);
        setPendingDelete(null);
        setCascadePending(null);
        await refresh();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to delete project";
        // 409 = "project has N workspace(s) attached; pass ?force=true to cascade-delete"
        if (!force && /workspace\(s\) attached/.test(msg)) {
          setPendingDelete(null);
          setCascadePending({ project, detail: msg });
          return;
        }
        addToast({ type: "error", title: msg });
      } finally {
        setDeletingProject(false);
      }
    },
    [addToast, refresh, t],
  );

  const handleConfirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    await performDelete(pendingDelete, false);
  }, [pendingDelete, performDelete]);

  const handleCascadeConfirm = useCallback(async () => {
    if (!cascadePending) return;
    await performDelete(cascadePending.project, true);
  }, [cascadePending, performDelete]);

  const handleSelectAndEnter = useCallback(
    (project: Project) => {
      setSelectedProjectId(project.id);
      router.push(`/projects/${project.id}`);
    },
    [router],
  );

  return (
    <PageFrame
      compact
      title={t("projects.configTitle")}
      leading={(
        <Button
          variant="outline"
          size="icon"
          onClick={() => {
            const pid = selectedProjectId();
            if (pid) router.push(`/projects/${pid}`);
            else router.push("/projects");
          }}
          aria-label={t("projects.backToWorkbench")}
          title={t("projects.backToWorkbench")}
        >
          <ChevronLeft size={16} />
        </Button>
      )}
      contentClassName="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6"
    >
        <aside className="enterprise-panel rounded-2xl p-3 space-y-2 self-start">
          <h2 className="text-xs uppercase tracking-wider text-muted-foreground px-2">
            {t("projects.listHeading")}
          </h2>
          <Button onClick={() => setCreateOpen(true)} size="sm" className="w-full">
            <Plus size={16} className="mr-1" />
            {t("projects.create")}
          </Button>
          {projects && projects.length > 3 && (
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("projects.searchPlaceholder")}
              className="w-full text-xs px-2 py-1.5 rounded border border-border-subtle bg-surface-input outline-none focus:border-brand"
            />
          )}
          {visibleProjects === null ? (
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : visibleProjects.length === 0 ? (
            <p className="text-sm text-muted-foreground px-2">{t("projects.empty")}</p>
          ) : (
            <ul className="space-y-1">
              {visibleProjects.map((p) => (
                <li key={p.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => setActiveId(p.id)}
                    className={cn(
                      "w-full text-left pl-3 pr-9 py-2 rounded-xl text-sm hover:bg-surface-hover transition",
                      activeId === p.id && "bg-brand/10 text-brand font-medium",
                    )}
                  >
                    <div className="truncate">{p.name}</div>
                    <div className="text-xs text-muted-foreground truncate">{p.repo_path}</div>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setPendingDelete(p);
                    }}
                    aria-label={t("projects.delete")}
                    title={t("projects.delete")}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-muted-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:bg-error/10 hover:text-error transition"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section>
          {activeProject ? (
            <div className="space-y-4">
              <Card className="enterprise-card rounded-2xl overflow-hidden">
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div>
                    <CardTitle className="text-brand">{activeProject.name}</CardTitle>
                    <CardDescription className="font-mono text-xs mt-1">{activeProject.repo_path}</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleCheckUpdate}
                      disabled={remoteChecking}
                      aria-label={t("projects.checkUpdate")}
                      title={t("projects.checkUpdate")}
                    >
                      <RefreshCw size={14} className={cn("mr-1", remoteChecking && "animate-spin")} />
                      {remoteChecking ? t("projects.checking") : t("projects.checkUpdate")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleSync}
                      disabled={syncing || !remoteStatus?.can_fast_forward}
                      aria-label={t("projects.sync")}
                      title={t("projects.sync")}
                    >
                      <DownloadCloud size={14} className={cn("mr-1", syncing && "animate-pulse")} />
                      {syncing ? t("projects.syncing") : t("projects.sync")}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          const res = await repairProject(activeProject.id);
                          addToast({
                            type: "success",
                            title: t("projects.repairToast").replace("{n}", String(res.issues_reset)),
                          });
                        } catch (err) {
                          const msg = err instanceof Error ? err.message : "Failed to repair";
                          addToast({ type: "error", title: msg });
                        }
                      }}
                      aria-label={t("projects.repair")}
                      title={t("projects.repairHelp")}
                    >
                      <Wrench size={14} className="mr-1" />
                      {t("projects.repair")}
                    </Button>
                    <Button size="sm" onClick={() => handleSelectAndEnter(activeProject)}>
                      {t("projects.enter")}
                      <ArrowRight size={16} className="ml-1" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                    <div>
                      <div className="text-muted-foreground text-xs">{t("projects.defaultBranch")}</div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono">{activeProject.default_branch}</span>
                        <RemoteUpdateBadge status={remoteStatus} checking={remoteChecking && remoteStatus === null} />
                      </div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-xs">{t("projects.origin")}</div>
                      <div className="font-mono truncate">{activeProject.origin_url ?? "—"}</div>
                    </div>
                  </div>
                  {stats && (
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs pt-2 border-t border-border-subtle">
                      <span>
                        <span className="text-muted-foreground">{STATS_LABELS.total}:</span>{" "}
                        <span className="font-semibold">{stats.issues_total}</span>
                      </span>
                      <span>
                        <span className="text-muted-foreground">{STATS_LABELS.open}:</span>{" "}
                        <span className="font-semibold">{stats.issues_open}</span>
                      </span>
                      <span>
                        <span className="text-muted-foreground">{STATS_LABELS.merged}:</span>{" "}
                        <span className="font-semibold text-success">{stats.issues_merged}</span>
                      </span>
                      <span>
                        <span className="text-muted-foreground">{STATS_LABELS.abandoned}:</span>{" "}
                        <span className="font-semibold text-muted-foreground">{stats.issues_abandoned}</span>
                      </span>
                    </div>
                  )}
                  <div className="space-y-2 pt-3 border-t border-border-subtle">
                    <button
                      type="button"
                      onClick={() => setBranchesOpen((v) => !v)}
                      className="flex w-full items-center gap-2 text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground transition"
                      aria-expanded={branchesOpen}
                    >
                      <GitBranchIcon size={14} />
                      {t("projects.branches")}
                      <ChevronDown
                        size={14}
                        className={cn("ml-auto transition-transform", !branchesOpen && "-rotate-90")}
                      />
                    </button>
                    {branchesOpen &&
                      (branchesLoading ? (
                        <Skeleton className="h-32 w-full" />
                      ) : (
                        <BranchListView branches={branches} defaultBranch={activeProject.default_branch} />
                      ))}
                  </div>
                </CardContent>
              </Card>
              <SetupScriptCard
                project={activeProject}
                onUpdated={(next) => {
                  setProjects((prev) => (prev ?? []).map((p) => (p.id === next.id ? next : p)));
                }}
              />
              <RunCommandCard
                project={activeProject}
                onUpdated={(next) => {
                  setProjects((prev) => (prev ?? []).map((p) => (p.id === next.id ? next : p)));
                }}
              />
              <Card className="enterprise-card rounded-2xl overflow-hidden">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <GitBranchIcon size={16} />
                    {t("projects.branches")}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {branchesLoading ? (
                    <div
                      data-density="projects-branches-tool-loading"
                      className="motion-essential relative flex min-h-[128px] items-center justify-center gap-2 overflow-hidden rounded-lg border border-status-tool/25 bg-status-tool/5 text-sm font-semibold text-text-muted"
                    >
                      <span
                        aria-hidden
                        className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool/70 to-transparent"
                      />
                      <AgentThinkingIndicator phase="tool" size={16} />
                      {t("projects.branches")}
                    </div>
                  ) : (
                    <BranchListView branches={branches} defaultBranch={activeProject.default_branch} />
                  )}
                </CardContent>
              </Card>
              {audit.length > 0 && (
                <Card className="enterprise-card rounded-2xl overflow-hidden">
                  <CardHeader>
                    <CardTitle className="text-base">{t("projects.recentActivity")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1 text-xs">
                      {audit.map((entry) => (
                        <li key={entry.id} className="flex items-center gap-2 font-mono">
                          <span
                            className={cn(
                              "px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider",
                              entry.event === "merged"
                                ? "bg-success/10 text-success"
                                : entry.event === "abandoned"
                                  ? "bg-muted text-muted-foreground"
                                  : entry.event === "deleted"
                                    ? "bg-error/10 text-error"
                                    : entry.event === "created"
                                      ? "bg-brand/10 text-brand"
                                      : "bg-foreground/10 text-foreground",
                            )}
                          >
                            {entry.event}
                          </span>
                          <span className="text-muted-foreground truncate">
                            {entry.issue_id ? entry.issue_id.slice(0, 8) : "—"}
                          </span>
                          {entry.sha && (
                            <span className="text-muted-foreground/70">@{entry.sha.slice(0, 7)}</span>
                          )}
                          <span className="ml-auto text-muted-foreground/70">
                            {formatRelative(entry.created_at)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </div>
          ) : (
            <Card>
              <CardContent className="p-4">
                <InteractionEmptyState
                  title={t("projects.selectHint")}
                  description={t("projects.selectHintDescription")}
                />
              </CardContent>
            </Card>
          )}
        </section>
      <CreateProjectDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(p: Project) => {
          setCreateOpen(false);
          setSelectedProjectId(p.id);
          refresh();
        }}
      />

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        title={t("projects.confirmDeleteTitle")}
        description={pendingDelete ? t("projects.confirmDeleteBody").replace("{name}", pendingDelete.name) : ""}
        confirmText={t("projects.delete")}
        cancelText={t("projects.cancel")}
        isLoading={deletingProject}
        onConfirm={() => void handleConfirmDelete()}
      />

      <ConfirmDialog
        open={cascadePending !== null}
        onOpenChange={(next) => {
          if (!next) setCascadePending(null);
        }}
        title={t("projects.confirmCascadeTitle")}
        description={
          cascadePending
            ? t("projects.confirmCascadeBody", { detail: cascadePending.detail })
            : ""
        }
        confirmText={t("projects.forceDelete")}
        cancelText={t("projects.keepProject")}
        variant="destructive"
        isLoading={deletingProject}
        onConfirm={() => void handleCascadeConfirm()}
      />
    </PageFrame>
  );
}
