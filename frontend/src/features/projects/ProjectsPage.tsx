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
import { deleteProject, getProjectBranches, listProjects, repairProject, updateProject } from "@/lib/api";
import { Textarea } from "@/components/ui/textarea";
import type { GitBranch, Project } from "@/lib/types";

import { CreateProjectDialog } from "./CreateProjectDialog";
import { BranchListView } from "./BranchListView";

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
  const [branches, setBranches] = useState<GitBranch[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null);

  const activeProject = useMemo(
    () => projects?.find((p) => p.id === activeId) ?? null,
    [projects, activeId],
  );

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
      return;
    }
    let cancelled = false;
    setBranchesLoading(true);
    getProjectBranches(activeId)
      .then((list) => {
        if (!cancelled) setBranches(list);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Failed to load branches";
          addToast({ type: "error", title: msg });
          setBranches([]);
        }
      })
      .finally(() => {
        if (!cancelled) setBranchesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeId, addToast]);

  const handleConfirmDelete = useCallback(
    async (force = false) => {
      if (!pendingDelete) return;
      try {
        await deleteProject(pendingDelete.id, force);
        addToast({ type: "success", title: t("projects.toastDeleted") });
        if (selectedProjectId() === pendingDelete.id) setSelectedProjectId(null);
        setPendingDelete(null);
        await refresh();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to delete project";
        // 409 = "project has N workspace(s) attached; pass ?force=true to cascade-delete"
        if (!force && /workspace\(s\) attached/.test(msg)) {
          if (window.confirm(t("projects.confirmCascade").replace("{detail}", msg))) {
            await handleConfirmDelete(true);
            return;
          }
        }
        addToast({ type: "error", title: msg });
      }
    },
    [pendingDelete, addToast, refresh, t],
  );

  const handleSelectAndEnter = useCallback(
    (project: Project) => {
      setSelectedProjectId(project.id);
      router.push("/");
    },
    [router],
  );

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b sticky top-0 z-10 bg-background/95 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => router.push("/")} aria-label={t("projects.backToWorkbench")}>
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

      <main className="max-w-6xl mx-auto px-6 py-6 grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6">
        <aside className="space-y-2">
          <h2 className="text-xs uppercase tracking-wider text-muted-foreground px-2">
            {t("projects.listHeading")}
          </h2>
          {projects === null ? (
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : projects.length === 0 ? (
            <p className="text-sm text-muted-foreground px-2">{t("projects.empty")}</p>
          ) : (
            <ul className="space-y-1">
              {projects.map((p) => (
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
                <CardContent className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                  <div>
                    <div className="text-muted-foreground text-xs">{t("projects.defaultBranch")}</div>
                    <div className="font-mono">{activeProject.default_branch}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs">{t("projects.origin")}</div>
                    <div className="font-mono truncate">{activeProject.origin_url ?? "—"}</div>
                  </div>
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
        onConfirm={() => handleConfirmDelete(false)}
      />
    </div>
  );
}
