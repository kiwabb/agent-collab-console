"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  createCodexIssue,
  deleteCodexIssue,
  exportCodexIssues,
  getCodexIssues,
  getProject,
  getRuntimeCatalog,
  getWorkspace,
  importCodexIssues,
} from "@/lib/api";
import type { CodexIssue, Project, RuntimeCatalog, Workspace } from "@/lib/types";
import { IssueGrid } from "@/features/issues/IssueGrid";
import { useToast } from "@/components/ui/toast";

interface Props {
  workspaceId: string;
}

export function WorkspaceBoard({ workspaceId }: Props) {
  const router = useRouter();
  const { addToast } = useToast();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [catalog, setCatalog] = useState<RuntimeCatalog | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const ws = await getWorkspace(workspaceId);
      setWorkspace(ws);
      const proj = ws.project_id ? await getProject(ws.project_id) : null;
      setProject(proj);
      const all = await getCodexIssues(workspaceId);
      setIssues(all);
      const cat = await getRuntimeCatalog().catch(() => null);
      setCatalog(cat);
    } catch (err) {
      addToast({ type: "error", title: "Failed to load workspace", message: err instanceof Error ? err.message : String(err) });
    } finally {
      setIsLoading(false);
    }
  }, [workspaceId, addToast]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = useCallback(
    async (
      title: string,
      description: string,
      _executor: "codex" | "claude",
      _provider: string | null,
      _model: string | null,
      baseBranch?: string | null,
    ) => {
      try {
        const issue = await createCodexIssue(workspaceId, title, description, baseBranch ?? null);
        setIssues((prev) => [issue, ...prev]);
        addToast({ type: "success", title: "Issue created" });
      } catch (err) {
        addToast({ type: "error", title: "Failed to create issue", message: err instanceof Error ? err.message : String(err) });
      }
    },
    [workspaceId, addToast]
  );

  const handleDelete = useCallback(
    async (issueId: string) => {
      try {
        await deleteCodexIssue(issueId);
        setIssues((prev) => prev.filter((i) => i.id !== issueId));
        addToast({ type: "success", title: "Issue deleted" });
      } catch (err) {
        addToast({ type: "error", title: "Failed to delete issue", message: err instanceof Error ? err.message : String(err) });
      }
    },
    [addToast]
  );

  const handleExport = useCallback(async () => {
    try {
      const data = await exportCodexIssues(workspaceId, "json");
      const blob = new Blob([data], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${workspace?.title ?? "workspace"}-issues.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      addToast({ type: "error", title: "Export failed", message: err instanceof Error ? err.message : String(err) });
    }
  }, [workspaceId, workspace, addToast]);

  const handleImport = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/json,.json";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        const imported = await importCodexIssues(workspaceId, text, "json");
        addToast({ type: "success", title: `Imported ${imported.length} issues` });
        await load();
      } catch (err) {
        addToast({ type: "error", title: "Import failed", message: err instanceof Error ? err.message : String(err) });
      }
    };
    input.click();
  }, [workspaceId, addToast, load]);

  return (
    <div className="px-8 py-6">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-black tracking-tight">{workspace?.title ?? "Workspace"}</h1>
          {project && (
            <p className="text-xs text-text-muted mt-1">
              {project.name} · {project.repo_path}
            </p>
          )}
        </div>
        <div className="flex gap-2 text-xs">
          <button
            type="button"
            onClick={() => void handleExport()}
            className="px-3 py-1.5 rounded border border-border-subtle hover:bg-surface-hover"
          >
            Export
          </button>
          <button
            type="button"
            onClick={handleImport}
            className="px-3 py-1.5 rounded border border-border-subtle hover:bg-surface-hover"
          >
            Import
          </button>
        </div>
      </div>
      <IssueGrid
        issues={issues}
        onSelect={(id) => router.push(`/issues/${id}`)}
        onCreate={handleCreate}
        onDelete={handleDelete}
        catalog={catalog}
        projectId={project?.id ?? null}
        projectDefaultBranch={project?.default_branch ?? null}
        isLoading={isLoading}
      />
    </div>
  );
}
