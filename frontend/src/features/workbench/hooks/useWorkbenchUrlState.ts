"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSelection } from "@/features/workbench/state/SelectionProvider";

const PROJECT_KEY = "selectedProjectId";
const WORKSPACE_KEY = "selectedWorkspaceId";
const ISSUE_KEY = "selectedIssueId";

/**
 * One-shot migration that translates legacy localStorage selection keys
 * into the new URL-driven routing. Runs once on mount.
 */
export function useWorkbenchUrlMigration() {
  const router = useRouter();
  const { issueId, workspaceId, projectId } = useSelection();

  useEffect(() => {
    if (typeof window === "undefined") return;
    let legacyIssue: string | null = null;
    let legacyWorkspace: string | null = null;
    let legacyProject: string | null = null;
    try {
      legacyIssue = window.localStorage.getItem(ISSUE_KEY);
      legacyWorkspace = window.localStorage.getItem(WORKSPACE_KEY);
      legacyProject = window.localStorage.getItem(PROJECT_KEY);
    } catch {
      return;
    }
    const target = legacyIssue
      ? `/issues/${legacyIssue}`
      : legacyWorkspace
        ? `/workspaces/${legacyWorkspace}`
        : legacyProject
          ? `/projects/${legacyProject}`
          : null;
    if (target && window.location.pathname === "/") {
      router.replace(target);
    }
    // Selection state hydrates from these on first read; no need to delete.
  }, [router, issueId, workspaceId, projectId]);
}
