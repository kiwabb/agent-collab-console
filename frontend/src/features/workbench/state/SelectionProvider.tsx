"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

const PROJECT_KEY = "selectedProjectId";
const WORKSPACE_KEY = "selectedWorkspaceId";
const ISSUE_KEY = "selectedIssueId";

export type IssueTab = "dag" | "tasks" | "artifacts" | "diff";

export interface SelectionState {
  projectId: string | null;
  workspaceId: string | null;
  issueId: string | null;
  tab: IssueTab;
}

export interface SelectionContextValue extends SelectionState {
  setProjectId: (id: string | null) => void;
  setWorkspaceId: (id: string | null) => void;
  setIssueId: (id: string | null) => void;
  setTab: (tab: IssueTab) => void;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

interface ProviderProps {
  children: React.ReactNode;
  initial?: Partial<SelectionState>;
}

function readLocal(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLocal(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export function SelectionProvider({ children, initial }: ProviderProps) {
  const [projectId, setProjectIdState] = useState<string | null>(initial?.projectId ?? null);
  const [workspaceId, setWorkspaceIdState] = useState<string | null>(initial?.workspaceId ?? null);
  const [issueId, setIssueIdState] = useState<string | null>(initial?.issueId ?? null);
  const [tab, setTabState] = useState<IssueTab>(initial?.tab ?? "dag");

  const setProjectId = useCallback((id: string | null) => {
    setProjectIdState(id);
    writeLocal(PROJECT_KEY, id);
  }, []);
  const setWorkspaceId = useCallback((id: string | null) => {
    setWorkspaceIdState(id);
    writeLocal(WORKSPACE_KEY, id);
  }, []);
  const setIssueId = useCallback((id: string | null) => {
    setIssueIdState(id);
    writeLocal(ISSUE_KEY, id);
  }, []);
  const setTab = useCallback((next: IssueTab) => setTabState(next), []);

  useEffect(() => {
    if (initial?.projectId !== undefined) {
      const nextProjectId = initial.projectId ?? null;
      setProjectIdState(nextProjectId);
      writeLocal(PROJECT_KEY, nextProjectId);
    } else {
      setProjectIdState(readLocal(PROJECT_KEY));
    }
    if (initial?.workspaceId !== undefined) {
      const nextWorkspaceId = initial.workspaceId ?? null;
      setWorkspaceIdState(nextWorkspaceId);
      writeLocal(WORKSPACE_KEY, nextWorkspaceId);
    } else {
      setWorkspaceIdState(readLocal(WORKSPACE_KEY));
    }
    if (initial?.issueId !== undefined) {
      const nextIssueId = initial.issueId ?? null;
      setIssueIdState(nextIssueId);
      writeLocal(ISSUE_KEY, nextIssueId);
    } else {
      setIssueIdState(readLocal(ISSUE_KEY));
    }
    if (initial?.tab) setTabState(initial.tab);
  }, [initial?.projectId, initial?.workspaceId, initial?.issueId, initial?.tab]);

  const value = useMemo<SelectionContextValue>(
    () => ({
      projectId,
      workspaceId,
      issueId,
      tab,
      setProjectId,
      setWorkspaceId,
      setIssueId,
      setTab,
    }),
    [projectId, workspaceId, issueId, tab, setProjectId, setWorkspaceId, setIssueId, setTab],
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used inside <SelectionProvider>");
  return ctx;
}
