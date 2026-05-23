"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { getCodexIssues, getCodexTasks, getProject, getRuntimeCatalog, getWorkspace } from "@/lib/api";
import type { CodexIssue, CodexTask, Project, RuntimeCatalog, Workspace } from "@/lib/types";
import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/providers/I18nProvider";
import { NewIssueDialog } from "./NewIssueDialog";
import { WorkspaceConsoleHeader, type IssueStatusFilter, type IssueSortMode } from "./WorkspaceConsoleHeader";
import { IssueListPanel } from "./IssueListPanel";

interface Props {
  workspaceId: string;
}

export default function WorkspaceConsole({ workspaceId }: Props) {
  const router = useRouter();
  const { addToast } = useToast();
  const { t } = useI18n();
  const { lastEvent } = useExecutionProcessesContext();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [newIssueOpen, setNewIssueOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<IssueStatusFilter>("all");
  const [sortMode, setSortMode] = useState<IssueSortMode>("updated");

  const refresh = useCallback(async (showLoader = false) => {
    if (showLoader) setIsLoading(true);
    try {
      const [allIssues, allTasks] = await Promise.all([
        getCodexIssues(workspaceId),
        getCodexTasks(workspaceId, null),
      ]);
      setIssues(allIssues);
      setTasks(allTasks);
    } catch {
      // Realtime refresh is best-effort; the full load path surfaces errors.
    } finally {
      if (showLoader) setIsLoading(false);
    }
  }, [workspaceId]);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const ws = await getWorkspace(workspaceId);
      setWorkspace(ws);
      const [proj, runtimeCatalog] = await Promise.all([
        ws.project_id ? getProject(ws.project_id) : Promise.resolve(null),
        getRuntimeCatalog().catch(() => null),
      ]);
      setProject(proj);
      setCatalog(runtimeCatalog);
      await refresh(false);
    } catch (err) {
      addToast({ type: "error", title: t("workspace.toast.loadFailed"), message: err instanceof Error ? err.message : String(err) });
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, refresh, addToast, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!lastEvent) return;
    const type = (lastEvent as { type?: string }).type;
    if (type === "issue_merged" || type === "issue_abandoned" || type === "task_created") {
      void refresh(false);
      return;
    }
    if (type === "task_status") {
      const status = String((lastEvent as { status?: string }).status || "").toLowerCase();
      if (status === "done" || status === "completed" || status === "failed" || status === "running") {
        void refresh(false);
      }
    }
  }, [lastEvent, refresh]);

  const visibleIssues = useMemo(() => {
    const filtered = issues.filter((issue) => {
      if (statusFilter === "all") return true;
      if (statusFilter === "awaiting") return issue.status === "awaiting_approval" || issue.status === "awaiting_review";
      if (statusFilter === "running") return issue.status === "in_progress" || issue.status === "running";
      if (statusFilter === "queued") return issue.status === "open" || issue.status === "queued" || issue.status === "pending";
      if (statusFilter === "done") return issue.status === "completed" || issue.status === "done";
      return issue.status === "failed";
    });
    return [...filtered].sort((a, b) => {
      if (sortMode === "phase") return String(a.current_phase).localeCompare(String(b.current_phase));
      if (sortMode === "status") return String(a.status).localeCompare(String(b.status));
      const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0;
      const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0;
      return bTime - aTime;
    });
  }, [issues, sortMode, statusFilter]);

  return (
    <div className="h-full min-h-0 overflow-hidden bg-[radial-gradient(circle_at_top_right,rgba(56,189,248,0.12),transparent_34%),linear-gradient(180deg,rgba(255,255,255,0.04),transparent_22%)]">
      <main className="mx-auto flex h-full max-w-7xl flex-col gap-4 px-5 py-5 lg:px-8">
        <WorkspaceConsoleHeader
          workspace={workspace}
          project={project}
          issues={issues}
          statusFilter={statusFilter}
          sortMode={sortMode}
          onStatusFilterChange={setStatusFilter}
          onSortModeChange={setSortMode}
          onNewIssue={() => setNewIssueOpen(true)}
        />
        <IssueListPanel
          issues={visibleIssues}
          allIssueCount={issues.length}
          tasks={tasks}
          project={project}
          isLoading={isLoading}
          onOpenIssue={(issueId) => router.push(`/issues/${issueId}`)}
          onClearFilter={() => setStatusFilter("all")}
        />
      </main>
      <NewIssueDialog
        open={newIssueOpen}
        onOpenChange={setNewIssueOpen}
        workspaceId={workspaceId}
        project={project}
        catalog={catalog}
        onCreated={(issue) => {
          setIssues((prev) => [issue, ...prev.filter((item) => item.id !== issue.id)]);
          void refresh(false);
        }}
      />
    </div>
  );
}
