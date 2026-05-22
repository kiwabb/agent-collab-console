"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronLeft, GitBranch as GitBranchIcon, Plus, Trash2, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import { deleteProject, getProjectAudit, getProjectBranches, getProjectStats, listProjects, repairProject, updateProject } from "@/lib/api";
import { emitDataEvent } from "@/lib/dataEvents";
import type { ProjectAuditEntry, ProjectStats } from "@/lib/types";
import { Textarea } from "@/components/ui/textarea";
import type { GitBranch, Project } from "@/lib/types";

import { CreateProjectDialog } from "./CreateProjectDialog";
import { BranchListView } from "./BranchListView";
import { STATS_LABELS } from "./statsLabels";

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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("projects.setupScript")}</CardTitle>
        <CardDescription>{t("projects.setupScriptHelp")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="npm install"
          rows={4}
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
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [audit, setAudit] = useState<ProjectAuditEntry[]>([]);
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
    <div className="min-h-screen bg-background">
      <header className="border-b sticky top-0 z-10 bg-background/95 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => {
              const pid = selectedProjectId();
              if (pid) router.push(`/projects/${pid}`);
              else router.push("/projects");
            }} aria-label={t("projects.backToWorkbench")}>
              <ChevronLeft size={16} />
              <span className="ml-1">{t("projects.backToWorkbench")}</span>
            </Button>
            <h1 className="text-lg font-semibold ml-2">{t("projects.title")}</h1>
          </div>
          <Button onClick={() => setCreateOpen(true)} size="sm">
            <Plus size={16} className="mr-1" />
            {t("projects.create")}
          </Button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6 items-start">
        <aside className="md:sticky md:top-20 md:self-start">
          <div className="bg-surface-raised border border-border-subtle rounded-lg p-3 space-y-2 min-h-[calc(100vh-9rem)]">
            <h2 className="text-xs uppercase tracking-wider text-muted-foreground px-1">
              {t("projects.listHeading")}
            </h2>
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
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => setActiveId(p.id)}
                      className={cn(
                        "w-full text-left px-3 py-2 rounded-md text-sm hover:bg-muted transition",
                        activeId === p.id && "bg-muted font-medium",
                      )}
                    >
                      <div className="truncate">{p.name}</div>
                      <div className="text-xs text-muted-foreground truncate">{p.repo_path}</div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <section>
          {activeProject ? (
            <div className="space-y-4">
              <Card>
                <CardHeader className="flex flex-row items-start justify-between space-y-0">
                  <div>
                    <CardTitle>{activeProject.name}</CardTitle>
                    <CardDescription className="font-mono text-xs mt-1">{activeProject.repo_path}</CardDescription>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => handleSelectAndEnter(activeProject)}>
                      {t("projects.enter")}
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
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setPendingDelete(activeProject)}
                      aria-label={t("projects.delete")}
                    >
                      <Trash2 size={16} />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 text-sm">
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                    <div>
                      <div className="text-muted-foreground text-xs">{t("projects.defaultBranch")}</div>
                      <div className="font-mono">{activeProject.default_branch}</div>
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
                </CardContent>
              </Card>
              <SetupScriptCard
                project={activeProject}
                onUpdated={(next) => {
                  setProjects((prev) => (prev ?? []).map((p) => (p.id === next.id ? next : p)));
                }}
              />
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <GitBranchIcon size={16} />
                    {t("projects.branches")}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {branchesLoading ? (
                    <Skeleton className="h-32 w-full" />
                  ) : (
                    <BranchListView branches={branches} defaultBranch={activeProject.default_branch} />
                  )}
                </CardContent>
              </Card>
              {audit.length > 0 && (
                <Card>
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
              <CardContent className="py-12 text-center text-muted-foreground">{t("projects.selectHint")}</CardContent>
            </Card>
          )}
        </section>
      </main>

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
        title="Cascade-delete this project?"
        description={
          cascadePending
            ? `${cascadePending.detail}\n\nForce-delete will remove the project plus all attached workspaces, issues, tasks and logs. This cannot be undone.`
            : ""
        }
        confirmText="Force delete"
        cancelText="Keep project"
        variant="destructive"
        isLoading={deletingProject}
        onConfirm={() => void handleCascadeConfirm()}
      />
    </div>
  );
}
