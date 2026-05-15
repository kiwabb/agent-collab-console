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
  const [projectId, setProjectIdState] = useState<string | null>(
    initial?.projectId ?? readLocal(PROJECT_KEY)
  );
  const [workspaceId, setWorkspaceIdState] = useState<string | null>(
    initial?.workspaceId ?? readLocal(WORKSPACE_KEY)
  );
  const [issueId, setIssueIdState] = useState<string | null>(
    initial?.issueId ?? readLocal(ISSUE_KEY)
  );
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
    if (initial?.projectId !== undefined) setProjectIdState(initial.projectId ?? null);
    if (initial?.workspaceId !== undefined) setWorkspaceIdState(initial.workspaceId ?? null);
    if (initial?.issueId !== undefined) setIssueIdState(initial.issueId ?? null);
    if (initial?.tab) setTabState(initial.tab);
  }, [initial?.projectId, initial?.workspaceId, initial?.issueId, initial?.tab]);

  const value = useMemo<SelectionContextValue>(
    () => ({ projectId, workspaceId, issueId, tab, setProjectId, setWorkspaceId, setIssueId, setTab }),
    [projectId, workspaceId, issueId, tab, setProjectId, setWorkspaceId, setIssueId, setTab]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used inside <SelectionProvider>");
  return ctx;
}
