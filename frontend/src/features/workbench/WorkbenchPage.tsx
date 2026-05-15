"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import type {
  Workspace,
  CodexIssue,
  CodexTask,
  ExecutionProcess,
  Approval,
  Artifact,
  HelpRequest,
  LogEvent,
  CodexTaskMessage,
  RunMode,
} from "@/lib/types";
import {
  getWorkspaces,
  createWorkspace,
  deleteWorkspace,
  deleteAllWorkspaces,
  getCodexIssues,
  getCodexTasks,
  getCodexIssueArtifacts,
  updateCodexIssuePhase,
  planIssue,
  getIssueGraph,
  saveIssueGraph,
  startIssueGraph,
  createCodexIssue,
  deleteCodexIssue,
  createCodexTask,
  runCodexTask,
  deleteCodexTask,
  sendCodexTaskMessage,
  chatCodexTask,
  refineCodexTask,
  rerunCodexTask,
  sendCodexTask,
  continueCodexTask,
  getExecutionProcessLogs,
  getExecutionProcessMessages,
  getCodexTaskMessages,
  getPendingApprovals,
  resolveApproval,
  getTaskHelpRequests,
  getExecutionProcesses,
  submitCodexTask,
  reviewCodexTask,
  terminateCodexTask,
  updateCodexTask,
} from "@/lib/api";
import { getRuntimeCatalog } from "@/lib/api";
import { ExecutionProcessesProvider } from "@/providers/ExecutionProcessesProvider";
import { useExecutionProcessesContext, isBusTaskStatusEvent, isBusTaskCreatedEvent, isBusIssueMergedEvent, isBusIssueAbandonedEvent } from "@/contexts/ExecutionProcessesContext";
import { WorkspaceGrid } from "@/features/workspaces/WorkspaceGrid";
import { GitInfoCard } from "@/features/issues/components/GitInfoCard";
import { IssueGrid } from "@/features/issues/IssueGrid";
import { TaskBoard } from "@/features/tasks/TaskBoard";
import { AgentCoordinationPanel } from "@/features/agents/AgentCoordinationPanel";
import { RunDetail } from "@/features/runs/RunDetail";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { ApprovalDialog } from "@/features/approvals/ApprovalDialog";
import { PHASE_CONFIG, type Phase } from "@/features/issues/phaseUtils";
import { pickLatestExecutionProcessForTask } from "@/lib/task-selection";
import { isTaskRuntimeActive } from "@/lib/task-selection";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { Kbd } from "@/components/ui/kbd";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { AsyncBoundary } from "@/components/ui/error-boundary";
import {
  Activity,
  RotateCcw,
  ChevronRight,
  Home,
  Layout,
  Settings,
  Bell,
  Terminal,
  AlertCircle,
  Search,
  Keyboard,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { motion, AnimatePresence } from "framer-motion";
import { createIssueAndInitialTask } from "@/features/workbench/workbenchActions";
import { KeyboardShortcutsModal } from "@/components/ui/keyboard-shortcuts-modal";
import { CommandPalette } from "@/components/ui/command-palette";
import { MacroRecorder, useMacros } from "@/components/ui/macro-recorder";
import { PresenceIndicator } from "@/components/ui/presence-indicator";
import { FadeIn } from "@/components/ui/animated-transitions";

type NavigationState = "home" | "workspace" | "issue";

function WorkbenchInner({
  currentWorkspaceId,
  onWorkspaceChange,
}: {
  currentWorkspaceId: string | null;
  onWorkspaceChange: (id: string | null) => void;
}) {
  const [view, setView] = useState<NavigationState>("home");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [issues, setIssues] = useState<CodexIssue[]>([]);
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [currentIssueId, setCurrentIssueId] = useState<string | null>(null);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedProcessId, setSelectedProcessId] = useState<string | null>(null);
  const [processLogs, setProcessLogs] = useState<LogEvent[]>([]);
  const [processMessages, setProcessMessages] = useState<CodexTaskMessage[]>([]);
  const [helpRequests, setHelpRequests] = useState<HelpRequest[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isTransitioningToArchitecture, setIsTransitioningToArchitecture] = useState(false);
  const [macroRecorderOpen, setMacroRecorderOpen] = useState(false);
  const { runMacro } = useMacros();
  const [isTransitioningToDevelopment, setIsTransitioningToDevelopment] = useState(false);
  const [isTransitioningToTesting, setIsTransitioningToTesting] = useState(false);
  const { addToast } = useToast();
  const [isLoadingLogs, setIsLoadingLogs] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isLoadingProcess, setIsLoadingProcess] = useState(false);
  const [isLoadingIssues, setIsLoadingIssues] = useState(false);
  const [isLoadingWorkspaces, setIsLoadingWorkspaces] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeCatalog, setRuntimeCatalog] = useState<import("@/lib/types").RuntimeCatalog | null>(null);
  const [connectionWarning, setConnectionWarning] = useState<string | null>(null);
  const [wasConnected, setWasConnected] = useState(false);
  const [currentProject, setCurrentProject] = useState<import("@/lib/types").Project | null>(null);
  const [allProjects, setAllProjects] = useState<import("@/lib/types").Project[]>([]);

  // Most-recently-used project ordering for the switcher: read the lastUsedAt
  // map once and re-render the dropdown by descending recency. Updated when
  // the user selects a project below.
  const orderedProjects = useMemo(() => {
    if (typeof window === "undefined") return allProjects;
    let mru: Record<string, number> = {};
    try {
      mru = JSON.parse(window.localStorage.getItem("projectLastUsedAt") || "{}");
    } catch {
      mru = {};
    }
    return [...allProjects].sort((a, b) => (mru[b.id] ?? 0) - (mru[a.id] ?? 0));
  }, [allProjects]);

  const { isConnected, lastEvent, executionProcessesAll } = useExecutionProcessesContext();
  // Optimistic placeholder for a freshly-created execution_process. Returned
  // by the backend immediately on /chat /refine /rerun but takes a beat to
  // arrive over the workspace WS. Without this fallback, selectedProcess
  // briefly resolves to null → RunDetail's `!process` early-return unmounts
  // the entire TabsContent → scroll position resets to top on re-mount.
  const [optimisticProcess, setOptimisticProcess] = useState<ExecutionProcess | null>(null);
  const { t } = useI18n();
  const router = useRouter();

  // Keyboard shortcuts
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  useKeyboardShortcuts([
    {
      key: "k",
      ctrlKey: true,
      action: () => setCommandPaletteOpen(true),
      description: "Open command palette",
    },
    {
      key: "m",
      ctrlKey: true,
      action: () => setMacroRecorderOpen(true),
      description: "Open macro recorder",
    },
    {
      key: "Escape",
      action: () => {
        if (currentTaskId) {
          setCurrentTaskId(null);
        } else if (view !== "home" && currentWorkspaceId) {
          if (view === "workspace") {
            onWorkspaceChange(null);
          } else if (view === "issue") {
            setView("workspace");
          }
        }
      },
      description: "Go back / Close panel",
    },
    {
      key: "h",
      action: () => {
        if (view !== "home") {
          onWorkspaceChange(null);
          setView("home");
        }
      },
      description: "Go to home",
    },
    {
      key: "w",
      action: () => {
        if (currentWorkspaceId && view === "home") {
          setView("workspace");
        }
      },
      description: "Go to workspace",
    },
    {
      key: "i",
      action: () => {
        if (currentIssueId && view === "workspace") {
          setView("issue");
        }
      },
      description: "Go to issue",
    },
  ]);

  // Watch connection status and show warning when disconnected
  useEffect(() => {
    if (isConnected) {
      setWasConnected(true);
      if (wasConnected && connectionWarning) {
        setConnectionWarning(t("nav.reconnectSuccess"));
        const timer = setTimeout(() => setConnectionWarning(null), 3000);
        return () => clearTimeout(timer);
      }
      setConnectionWarning(null);
    } else if (wasConnected && currentWorkspaceId) {
      setConnectionWarning(t("nav.connectionLost"));
    }
  }, [isConnected, currentWorkspaceId, t, wasConnected, connectionWarning]);

  const currentWorkspace = workspaces.find(w => w.id === currentWorkspaceId);
  const currentIssue = issues.find((i) => i.id === currentIssueId) ?? null;

  const loadWorkspaceData = useCallback(async (workspaceId: string) => {
    setIsLoadingIssues(true);
    try {
      const [iss, tks] = await Promise.all([
        getCodexIssues(workspaceId),
        getCodexTasks(workspaceId, null),
      ]);
      setIssues(iss);
      setTasks(tks);
      const hrs: HelpRequest[] = [];
      const helpResults = await Promise.allSettled(
        tks.map((task) => getTaskHelpRequests(task.id))
      );
      for (const result of helpResults) {
        if (result.status === "fulfilled") {
          hrs.push(...result.value);
        }
      }
      setHelpRequests(hrs);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load workspace data";
      setError(msg);
      addToast({ type: "error", title: "Failed to load workspace", message: msg });
    } finally {
      setIsLoadingIssues(false);
    }
  }, []);

  const handleTaskSubmitForReview = useCallback(async () => {
    if (!currentTaskId) return;
    try {
      const updated = await submitCodexTask(currentTaskId);
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      addToast({ type: "success", title: "Task submitted for review" });
      if (currentWorkspaceId) {
        await loadWorkspaceData(currentWorkspaceId);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to submit task for review";
      setError(msg);
      addToast({ type: "error", title: "Failed to submit for review", message: msg });
    }
  }, [currentTaskId, currentWorkspaceId, loadWorkspaceData]);

  const handleTaskReview = useCallback(async (decision: "approve" | "reject", comment: string) => {
    if (!currentTaskId) return;
    try {
      const updated = await reviewCodexTask(currentTaskId, decision, comment);
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
    }
  }, [currentTaskId]);

  const currentTask = tasks.find((task) => task.id === currentTaskId) ?? null;
  const currentTasks = currentIssueId ? tasks.filter((t) => t.issue_id === currentIssueId) : [];
  const hasRequirementsArtifacts = artifacts.some((artifact) =>
    artifact.name === "pm/requirement.md" || artifact.name === "pm/prd.json" || artifact.name === "pm/prd.md"
  );
  const hasArchitectureArtifacts = artifacts.some((artifact) =>
    artifact.name === "architect/system_design.json" || artifact.name === "architect/implementation_plan.json"
  );
  
  // Check if ProductManager task is done for requirements phase
  const pmTask = currentTasks.find((t) => t.role === "product_manager");
  const isPmTaskDone = pmTask?.status === "done";

  // All engineer tasks for the issue must be 'done' before testing transition
  const engineerTasks = currentTasks.filter((t) => t.role === "engineer");
  const allEngineerTasksDone = engineerTasks.length > 0 && engineerTasks.every((t) => t.status === "done");

  // Parse qa_plan.json (which actually stores the QAReportDocument) for status badge
  const qaReportStatus = useMemo<"passed" | "failed" | "blocked" | "needs_follow_up" | null>(() => {
    const qaPlan = artifacts.find((a) => a.name === "qa/qa_plan.json");
    if (!qaPlan || typeof qaPlan.content !== "string") return null;
    try {
      const parsed = JSON.parse(qaPlan.content);
      const status = parsed?.status;
      if (status === "passed" || status === "failed" || status === "blocked" || status === "needs_follow_up") {
        return status;
      }
    } catch {
      return null;
    }
    return null;
  }, [artifacts]);
  
  const hasActiveIssueTask = currentTasks.some((task) => {
    return isTaskRuntimeActive(task, Object.values(executionProcessesAll) as ExecutionProcess[]);
  });
  const currentIssueTaskIds = useMemo(
    () => new Set(currentTasks.map((task) => task.id)),
    [currentTasks],
  );
  const currentIssueCompletedProcessKey = useMemo(() => {
    const terminalStatuses = new Set(["completed", "done", "failed", "killed"]);
    return (Object.values(executionProcessesAll) as ExecutionProcess[])
      .filter((process) => currentIssueTaskIds.has(process.task_id))
      .filter((process) => terminalStatuses.has(String(process.status || "").toLowerCase()))
      .map((process) => `${process.id}:${process.status}:${process.updated_at || process.completed_at || ""}`)
      .sort()
      .join("|");
  }, [currentIssueTaskIds, executionProcessesAll]);
  const selectedProcess: ExecutionProcess | null = selectedProcessId
    ? ((Object.values(executionProcessesAll) as ExecutionProcess[]).find(
        (p) => p.id === selectedProcessId,
      ) ??
      (optimisticProcess?.id === selectedProcessId ? optimisticProcess : null))
    : null;
  // Once the WS workspace stream catches up and the real EP appears in
  // executionProcessesAll, drop the placeholder so we don't hold a stale copy.
  useEffect(() => {
    if (!optimisticProcess) return;
    const arrived = (Object.values(executionProcessesAll) as ExecutionProcess[]).some(
      (p) => p.id === optimisticProcess.id,
    );
    if (arrived) setOptimisticProcess(null);
  }, [optimisticProcess, executionProcessesAll]);
  const liveProcessLogs = selectedProcess?.logs ?? [];
  const liveProcessMessages = selectedProcess?.messages ? Object.values(selectedProcess.messages) : [];
  const displayedProcessLogs = useMemo(() => {
    const byId = new Map<string, LogEvent>();
    for (const log of [...processLogs, ...liveProcessLogs]) {
      byId.set(log.id || `${log.created_at}-${log.stream}-${log.content}`, log);
    }
    return Array.from(byId.values()).sort((a, b) => {
      const left = a.created_at ? new Date(a.created_at).getTime() : 0;
      const right = b.created_at ? new Date(b.created_at).getTime() : 0;
      return left - right;
    });
  }, [processLogs, liveProcessLogs]);
  const displayedProcessMessages = useMemo(() => {
    const byId = new Map<string, CodexTaskMessage>();
    for (const message of [...processMessages, ...liveProcessMessages]) {
      byId.set(message.id, message);
    }
    return Array.from(byId.values()).sort((a, b) => {
      const left = a.created_at ? new Date(a.created_at).getTime() : 0;
      const right = b.created_at ? new Date(b.created_at).getTime() : 0;
      return left - right;
    });
  }, [processMessages, liveProcessMessages]);

  useEffect(() => {
    if (!currentProject) return;
    setIsLoadingWorkspaces(true);
    getWorkspaces(currentProject.id)
      .then(setWorkspaces)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoadingWorkspaces(false));
  }, [currentProject]);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setView("home");
      return;
    }
    loadWorkspaceData(currentWorkspaceId);
  }, [currentWorkspaceId, loadWorkspaceData]);

  useEffect(() => {
    getRuntimeCatalog().then(setRuntimeCatalog).catch(() => setRuntimeCatalog(null));
  }, []);

  useEffect(() => {
    if (!currentIssueId) {
      setArtifacts([]);
      return;
    }
    getCodexIssueArtifacts(currentIssueId)
      .then(setArtifacts)
      .catch(() => setArtifacts([]));
  }, [currentIssueId]);

  useEffect(() => {
    if (!currentIssueId || !currentIssueCompletedProcessKey) {
      return;
    }
    getCodexIssueArtifacts(currentIssueId)
      .then(setArtifacts)
      .catch(() => setArtifacts([]));
  }, [currentIssueId, currentIssueCompletedProcessKey]);

  useEffect(() => {
    if (!lastEvent) return;

    if (isBusTaskStatusEvent(lastEvent)) {
      const event = lastEvent;
      setTasks((prev) =>
        prev.map((t) =>
          t.id === event.task_id
            ? { ...t, status: event.status, review_comment: event.review_comment }
            : t
        )
      );
    } else if (isBusTaskCreatedEvent(lastEvent)) {
      const event = lastEvent;
      setTasks((prev) => {
        if (prev.some((t) => t.id === event.task.id)) return prev;
        return [...prev, event.task as unknown as CodexTask];
      });
    } else if (isBusIssueMergedEvent(lastEvent)) {
      const event = lastEvent;
      setIssues((prev) =>
        prev.map((i) =>
          i.id === event.issue_id
            ? { ...i, git_merge_status: "merged", git_last_commit_sha: event.sha }
            : i,
        ),
      );
    } else if (isBusIssueAbandonedEvent(lastEvent)) {
      const event = lastEvent;
      setIssues((prev) =>
        prev.map((i) =>
          i.id === event.issue_id
            ? { ...i, git_merge_status: "abandoned", git_worktree_path: null }
            : i,
        ),
      );
    }
  }, [lastEvent]);

  // task_id is what messages are scoped by. Resolve it through selectedProcess
  // which already falls back to optimisticProcess when the WS hasn't synced the
  // freshly-created EP yet — otherwise on chat send we'd briefly miss the
  // task_id, fall back to the EP-scoped messages endpoint (returns empty for a
  // brand-new EP), wipe processMessages, and flash a loading spinner.
  const selectedTaskId = selectedProcess?.task_id ?? null;
  useEffect(() => {
    if (!selectedProcessId) {
      setIsLoadingLogs(false);
      setIsLoadingMessages(false);
      setProcessLogs([]);
      setProcessMessages([]);
      return;
    }
    let cancelled = false;
    // Only flip loading state when we don't already have content to show —
    // avoids the visual "flash to empty state" on every chat send.
    if (processLogs.length === 0) setIsLoadingLogs(true);
    if (processMessages.length === 0) setIsLoadingMessages(true);
    setIsLoadingProcess(true);
    // Logs are EP-scoped; messages are task-scoped so chat history persists
    // across re-runs / follow-up runs that spawn new execution processes.
    const messagesPromise = selectedTaskId
      ? getCodexTaskMessages(selectedTaskId)
      : getExecutionProcessMessages(selectedProcessId);
    Promise.all([getExecutionProcessLogs(selectedProcessId), messagesPromise])
      .then(([logs, msgs]) => {
        if (cancelled) return;
        setProcessLogs(logs);
        setProcessMessages(msgs);
      })
      .catch(() => {
        if (cancelled) return;
        setProcessLogs([]);
        setProcessMessages([]);
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoadingLogs(false);
        setIsLoadingMessages(false);
        setIsLoadingProcess(false);
      });
    return () => {
      cancelled = true;
    };
    // selectedTaskId is intentionally a dep: when EP id changes we want fetch;
    // when task_id later becomes available (optimistic → real), fetch again
    // task-scoped (correct content) so the temporary EP-scoped result is replaced.
    // processLogs / processMessages are intentionally NOT deps to avoid loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProcessId, selectedTaskId]);

  useEffect(() => {
    getPendingApprovals()
      .then((res) => setPendingApprovals(res.pending))
      .catch(() => setPendingApprovals([]));
  }, []);

  // Resolve selected project from URL `?project=...` (shareable) first, then
  // fall back to localStorage. Persist the resolution in both places so they
  // stay in sync.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const fromUrl = url.searchParams.get("project");
    const fromStorage = window.localStorage.getItem("selectedProjectId");
    const pid = fromUrl || fromStorage;
    if (!pid) {
      router.push("/projects");
      return;
    }
    if (fromUrl && fromUrl !== fromStorage) {
      window.localStorage.setItem("selectedProjectId", fromUrl);
    } else if (!fromUrl && fromStorage) {
      url.searchParams.set("project", fromStorage);
      window.history.replaceState(null, "", url.toString());
    }
    import("@/lib/api").then(({ getProject, listProjects }) => {
      getProject(pid).then(setCurrentProject).catch(() => {
        window.localStorage.removeItem("selectedProjectId");
        router.push("/projects");
      });
      listProjects().then(setAllProjects).catch(() => setAllProjects([]));
    });
  }, [router]);

  // Cross-tab sync: react when selectedProjectId changes in another tab.
  useEffect(() => {
    function onStorage(event: StorageEvent) {
      if (event.key !== "selectedProjectId") return;
      const next = event.newValue;
      if (!next) {
        router.push("/projects");
        return;
      }
      import("@/lib/api").then(({ getProject }) => getProject(next).then(setCurrentProject));
      const url = new URL(window.location.href);
      url.searchParams.set("project", next);
      window.history.replaceState(null, "", url.toString());
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [router]);

  async function handleCreateWorkspace(title: string) {
    const projectId = typeof window !== "undefined" ? window.localStorage.getItem("selectedProjectId") : null;
    if (!projectId) {
      addToast({ type: "warning", title: t("projects.selectProjectFirst") });
      router.push("/projects");
      return;
    }
    try {
      const ws = await createWorkspace(title, projectId);
      setWorkspaces((prev) => [...prev, ws]);
      handleSelectWorkspace(ws.id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create workspace";
      setError(msg);
      addToast({ type: "error", title: "Failed to create workspace", message: msg });
    }
  }

  const handleSelectWorkspace = useCallback((id: string) => {
    onWorkspaceChange(id);
    setView("workspace");
    setCurrentIssueId(null);
    setCurrentTaskId(null);
    setSelectedProcessId(null);
    setIsLoadingLogs(false);
    setIsLoadingMessages(false);
    setIsLoadingProcess(false);
    setProcessLogs([]);
    setProcessMessages([]);
  }, [onWorkspaceChange]);

  async function handleDeleteWorkspace(id: string) {
    try {
      await deleteWorkspace(id);
      setWorkspaces((prev) => prev.filter((w) => w.id !== id));
      addToast({ type: "success", title: "Workspace deleted" });
      if (currentWorkspaceId === id) {
        onWorkspaceChange(null);
        setView("home");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to delete workspace";
      setError(msg);
      addToast({ type: "error", title: "Failed to delete workspace", message: msg });
    }
  }

  async function handleCreateIssue(
    title: string,
    description: string,
    executor: "codex" | "claude",
    provider: string | null,
    model: string | null,
    baseBranch?: string | null,
  ) {
    if (!currentWorkspaceId) return;
    try {
      const { issue, initialTask, executionProcess } = await createIssueAndInitialTask({
        workspaceId: currentWorkspaceId,
        title,
        description,
        executor,
        issueTitle: `${t("phase.requirements")} - ${title}`,
        createCodexIssue,
        createCodexTask,
        runCodexTask,
        provider,
        model,
        baseBranch,
      });
      setIssues((prev) => [...prev, issue]);
      setTasks((prev) => [...prev, initialTask]);
      handleSelectIssue(issue.id);
      setSelectedProcessId(executionProcess.id);
      setCurrentTaskId(initialTask.id);
      addToast({ type: "success", title: "Issue created" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create issue";
      setError(msg);
      addToast({ type: "error", title: "Failed to create issue", message: msg });
    }
  }

  const handleSelectIssue = useCallback((id: string) => {
    setCurrentIssueId(id);
    setView("issue");
    setCurrentTaskId(null);
  }, []);

  const handleSelectTask = useCallback((id: string) => {
    const task = tasks.find(t => t.id === id);
    const localProcess = pickLatestExecutionProcessForTask(
      Object.values(executionProcessesAll) as ExecutionProcess[],
      id,
    );

    if (localProcess) {
      setSelectedProcessId(localProcess.id);
    } else if (task?.last_execution_process_id) {
      setSelectedProcessId(task.last_execution_process_id);
    } else {
      setSelectedProcessId(null);
    }

    setCurrentTaskId(id);
  }, [tasks, executionProcessesAll]);

  async function handleChangePhase(phase: string) {
    if (!currentIssue) return;
    try {
      const updated = await updateCodexIssuePhase(currentIssue.id, phase);
      setIssues((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change phase");
    }
  }

  async function handleDeleteIssue(issueId: string) {
    if (!currentWorkspaceId) return;
    try {
      await deleteCodexIssue(issueId);
      if (currentIssueId === issueId) {
        setCurrentIssueId(null);
        setCurrentTaskId(null);
        setSelectedProcessId(null);
        setProcessLogs([]);
        setProcessMessages([]);
        setArtifacts([]);
        setHelpRequests([]);
        setIsRunning(false);
        setView("workspace");
      }
      setView("workspace");
      await loadWorkspaceData(currentWorkspaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete issue");
    }
  }

  // Legacy "transition to phase X" handlers now share one path: plan the
  // workflow DAG (if missing), then start it. The phase label is updated
  // locally for kanban display purposes.
  const startGraphForPhase = useCallback(
    async (
      phase: string,
      setBusy: (busy: boolean) => void,
      toastOk: string,
      toastErr: string,
    ) => {
      if (!currentIssue) return;
      setBusy(true);
      try {
        let graph = await getIssueGraph(currentIssue.id);
        if (graph === null) {
          const proposed = await planIssue(currentIssue.id);
          graph = await saveIssueGraph(currentIssue.id, proposed);
        }
        await startIssueGraph(currentIssue.id);
        setIssues((prev) =>
          prev.map((issue) =>
            issue.id === currentIssue.id ? { ...issue, current_phase: phase } : issue
          )
        );
        const freshArtifacts = await getCodexIssueArtifacts(currentIssue.id);
        setArtifacts(freshArtifacts);
        addToast({ type: "success", title: toastOk });
      } catch (err) {
        const msg = err instanceof Error ? err.message : toastErr;
        setError(msg);
        addToast({ type: "error", title: toastErr, message: msg });
      } finally {
        setBusy(false);
      }
    },
    [currentIssue]
  );

  const handleTransitionToArchitecture = useCallback(
    () => startGraphForPhase("architecture", setIsTransitioningToArchitecture, "Transitioned to Architecture", "Failed to transition"),
    [startGraphForPhase]
  );
  const handleTransitionToDevelopment = useCallback(
    () => startGraphForPhase("development", setIsTransitioningToDevelopment, "Transitioned to Development", "Failed to transition"),
    [startGraphForPhase]
  );
  const handleTransitionToTesting = useCallback(
    () => startGraphForPhase("testing", setIsTransitioningToTesting, "已流转到测试阶段", "流转失败"),
    [startGraphForPhase]
  );

  async function handleRunPhaseRole(
    phase: string,
    executor: "codex" | "claude",
    provider: string | null,
    model: string | null
  ) {
    if (!currentIssue || !currentWorkspaceId) return;
    setIsRunning(true);
    try {
      const config = PHASE_CONFIG[phase as Phase] ?? PHASE_CONFIG.requirements;
      const task = await createCodexTask(
        currentWorkspaceId,
        `${t(config.labelKey)} - ${currentIssue.title}`,
        currentIssue.description || "",
        null,
        executor,
        config.role,
        currentIssue.id,
        phase,
        provider,
        model,
      );
      setTasks((prev) => [...prev, task]);
      const executionProcess = await runCodexTask(task.id, { executor, provider, model });
      setSelectedProcessId(executionProcess.id);
      setCurrentTaskId(task.id);
      await loadWorkspaceData(currentWorkspaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run task");
    } finally {
      setIsRunning(false);
    }
  }

  async function handleResolveApproval(
    itemId: string,
    decision: string,
    feedback: string | null,
  ) {
    try {
      await resolveApproval(itemId, decision, feedback);
      setPendingApprovals((prev) => prev.filter((a) => a.id !== itemId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve approval");
    }
  }

  const [lastResolvedMode, setLastResolvedMode] = useState<"chat" | "refine" | null>(null);

  const handleSendMessage = useCallback(async (content: string, mode: RunMode = "auto") => {
    if (!selectedProcess) return;
    try {
      let result;
      if (mode === "refine") {
        result = await refineCodexTask(selectedProcess.task_id, content);
        setLastResolvedMode(null);
      } else if (mode === "chat") {
        result = await chatCodexTask(selectedProcess.task_id, content);
        setLastResolvedMode(null);
      } else {
        result = await sendCodexTask(selectedProcess.task_id, content);
        if (result?.resolved_mode) setLastResolvedMode(result.resolved_mode);
      }
      // Optimistically append the just-sent user message (and assistant reply
      // if the backend already finalized in mock mode) so the chat thread
      // updates without a second round trip. The task-scoped GET in the
      // selectedProcessId effect below will deduplicate by id.
      setProcessMessages((prev) => {
        const byId = new Map(prev.map((m) => [m.id, m] as const));
        if (result?.message?.id) byId.set(result.message.id, result.message as CodexTaskMessage);
        if (result?.assistant_message?.id) {
          byId.set(result.assistant_message.id, result.assistant_message as CodexTaskMessage);
        }
        return Array.from(byId.values());
      });
      // Seed an optimistic placeholder for the new execution_process so
      // selectedProcess resolves immediately (avoids RunDetail unmounting
      // while the workspace WS catches up).
      const newProcess = result?.execution_process;
      if (newProcess?.id) {
        setOptimisticProcess(newProcess as ExecutionProcess);
        setSelectedProcessId(newProcess.id);
      }
      // No further fetch here — the selectedProcessId effect will pull
      // task-scoped messages + EP-scoped logs once.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
      const titleMap: Record<RunMode, string> = { auto: "发送失败", chat: "对话失败", refine: "修订失败" };
      addToast({ type: "error", title: titleMap[mode], message: err instanceof Error ? err.message : undefined });
    }
  }, [selectedProcess, currentWorkspaceId]);


  return (
    <div className="flex flex-col h-screen overflow-hidden bg-background font-sans">
      {/* Universal Topbar */}
      <header className="h-16 shrink-0 flex items-center justify-between px-8 border-b border-border-subtle bg-surface/80 backdrop-blur-xl z-50">
        <div className="flex items-center gap-8">
          <div 
            className="flex items-center gap-3 cursor-pointer hover:opacity-80 transition-opacity"
            onClick={() => setView("home")}
          >
            <div className="size-8 rounded-xl bg-brand flex items-center justify-center shadow-lg shadow-brand/20">
              <Activity size={18} className="text-background" />
            </div>
            <h1 className="text-lg font-black tracking-tighter text-foreground">JACKMOUSE.AI</h1>
          </div>

          <nav className="flex items-center gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <button
                    className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold text-text-muted hover:bg-surface-hover transition-all max-w-[220px] truncate"
                    aria-label={t("workbench.changeProject")}
                  />
                }
              >
                <span className="opacity-60">{t("workbench.projectSwitcher")}:</span>
                <span className="truncate text-foreground">{currentProject?.name ?? "—"}</span>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[220px]">
                {orderedProjects.map((p) => (
                  <DropdownMenuItem
                    key={p.id}
                    onClick={() => {
                      if (p.id === currentProject?.id) return;
                      // Warn if anything is mid-flight: switching project resets the
                      // visible workspace so a running task would lose its UI surface.
                      const hasRunning = tasks.some((tk) => tk.status === "running" || tk.status === "responding");
                      if (hasRunning && !window.confirm(t("workbench.switchWhileRunning"))) {
                        return;
                      }
                      if (typeof window !== "undefined") {
                        window.localStorage.setItem("selectedProjectId", p.id);
                        const url = new URL(window.location.href);
                        url.searchParams.set("project", p.id);
                        window.history.replaceState(null, "", url.toString());
                        // Stamp MRU so this project floats to the top next time.
                        try {
                          const mru = JSON.parse(window.localStorage.getItem("projectLastUsedAt") || "{}");
                          mru[p.id] = Date.now();
                          window.localStorage.setItem("projectLastUsedAt", JSON.stringify(mru));
                        } catch {
                          /* localStorage misconfigured — ignore */
                        }
                      }
                      setCurrentProject(p);
                      // Reset workbench navigation so we don't keep a stale workspace selected.
                      onWorkspaceChange(null);
                      setView("home");
                    }}
                  >
                    <span className="truncate font-medium">{p.name}</span>
                    {currentProject?.id === p.id && (
                      <span className="ml-auto text-[10px] uppercase tracking-wider text-brand">
                        {t("projects.branchCurrent")}
                      </span>
                    )}
                  </DropdownMenuItem>
                ))}
                {allProjects.length > 0 && <DropdownMenuSeparator />}
                <DropdownMenuItem onClick={() => router.push("/projects")}>
                  {t("workbench.manageProjects")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <ChevronRight size={14} className="text-text-muted/40" />
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setView("home")}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold transition-all",
                    view === "home" ? "bg-brand/10 text-brand" : "text-text-muted hover:bg-surface-hover"
                  )}
                >
                  <Home size={14} />
                  {t("nav.home")}
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <span className="flex items-center gap-1.5">
                  {t("nav.home")}
                  <Kbd>H</Kbd>
                </span>
              </TooltipContent>
            </Tooltip>

            {currentWorkspaceId && (
              <>
                <ChevronRight size={14} className="text-text-muted/40" />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={() => setView("workspace")}
                      className={cn(
                        "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-bold transition-all max-w-[150px] truncate",
                        view === "workspace" ? "bg-brand/10 text-brand" : "text-text-muted hover:bg-surface-hover"
                      )}
                    >
                      <Layout size={14} />
                      {currentWorkspace?.title || t("nav.workspace")}
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    <span className="flex items-center gap-1.5">
                      {t("nav.workspace")}
                      <Kbd>W</Kbd>
                    </span>
                  </TooltipContent>
                </Tooltip>
              </>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-4 text-text-muted" data-tour="shortcuts">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setCommandPaletteOpen(true)}
                  className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors cursor-pointer outline-none"
                  aria-label="Command Palette"
                >
                  <Search size={18} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <span className="flex items-center gap-1.5">
                  Command Palette
                  <Kbd>Ctrl</Kbd><Kbd>K</Kbd>
                </span>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => setMacroRecorderOpen(true)}
                  className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors cursor-pointer outline-none"
                  aria-label="Keyboard Macros"
                >
                  <Keyboard size={18} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <span className="flex items-center gap-1.5">
                  Macros
                  <Kbd>Ctrl</Kbd><Kbd>M</Kbd>
                </span>
              </TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={() => router.push("/settings")}
                  className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors cursor-pointer outline-none"
                  aria-label={t("settings.title")}
                >
                  <Settings size={18} />
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                <span className="flex items-center gap-1.5">
                  {t("settings.title")}
                  <Kbd>S</Kbd>
                </span>
              </TooltipContent>
            </Tooltip>
          </div>

          <div className="h-4 w-px bg-border-subtle" />

          <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-surface-raised border border-border-subtle">
            <div className={cn(
              "size-2 rounded-full",
              isConnected ? "bg-success animate-pulse" : "bg-error"
            )} />
            <span className="text-[10px] font-black uppercase tracking-widest text-text-secondary">
              {isConnected ? t("nav.coreActive") : t("nav.coreOffline")}
            </span>
          </div>
        </div>
      </header>

      <main className="flex-1 min-h-0 relative overflow-hidden bg-background flex flex-col">
        {error && (
          <div className="mx-8 mt-6 p-4 rounded-xl bg-error/10 border border-error/20 flex items-center justify-between animate-in slide-in-from-top-4 duration-300 gap-4">
            <div className="flex items-center gap-3">
              <div className="size-8 rounded-lg bg-error/10 flex items-center justify-center">
                <AlertCircle size={16} className="text-error" />
              </div>
              <div className="min-w-0">
                <p className="text-[10px] font-black uppercase tracking-widest text-error opacity-60">
                  {t("run.error")}
                </p>
                <p className="text-xs font-bold text-error break-words">{error}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => {
                  setError(null);
                  if (currentWorkspaceId) loadWorkspaceData(currentWorkspaceId);
                }}
                className="px-3 py-1.5 rounded-lg bg-error/20 text-error text-[10px] font-bold uppercase tracking-widest hover:bg-error/30 transition-all"
              >
                {t("settings.retryConnection")}
              </button>
              <button
                onClick={() => setError(null)}
                className="p-2 hover:bg-error/10 rounded-lg text-error/60 hover:text-error transition-all"
              >
                <RotateCcw size={14} className="rotate-45" />
              </button>
            </div>
          </div>
        )}

        {connectionWarning && (
          <div className="mx-8 mt-6 p-4 rounded-xl bg-warning/10 border border-warning/20 flex items-center gap-3 animate-in slide-in-from-top-4 duration-300">
            <div className="size-8 rounded-lg bg-warning/10 flex items-center justify-center">
              <AlertCircle size={16} className="text-warning" />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-black uppercase tracking-widest text-warning opacity-60">
                {t("nav.coreOffline")}
              </p>
              <p className="text-xs font-bold text-warning break-words">{connectionWarning}</p>
            </div>
          </div>
        )}

        {view === "home" && (
          <div className="h-full overflow-y-auto no-scrollbar">
            <div className="p-8 max-w-7xl mx-auto w-full">
              <FadeIn direction="up" delay={0.1}>
                <div className="mb-6">
                  <h1 className="text-3xl font-bold tracking-tight">工作区</h1>
                  <p className="text-sm text-muted-foreground mt-1">选择或创建一个工作区开始</p>
                </div>
              </FadeIn>
              <FadeIn direction="up" delay={0.1} className="w-full">
                <WorkspaceGrid
              workspaces={workspaces}
              onSelect={handleSelectWorkspace}
              onCreate={handleCreateWorkspace}
              onDelete={handleDeleteWorkspace}
              isLoading={isLoadingWorkspaces}
                />
              </FadeIn>
            </div>
          </div>
        )}

        {view === "workspace" && currentWorkspaceId && (
          <div className="h-full overflow-y-auto no-scrollbar">
            <IssueGrid
              issues={issues}
              onSelect={handleSelectIssue}
              onCreate={handleCreateIssue}
              onDelete={handleDeleteIssue}
              catalog={runtimeCatalog}
              projectId={currentProject?.id ?? null}
              projectDefaultBranch={currentProject?.default_branch ?? null}
              isLoading={isLoadingIssues}
            />
          </div>
        )}

        {view === "issue" && currentIssueId && (
          <div className="h-full overflow-y-auto">
            {currentIssue && (
              <div className="px-8 pt-4">
                <GitInfoCard
                  issue={currentIssue}
                  onIssueUpdated={(next) =>
                    setIssues((prev) => prev.map((i) => (i.id === next.id ? next : i)))
                  }
                />
              </div>
            )}
            <TaskBoard
              tasks={currentTasks}
              executionProcesses={Object.values(executionProcessesAll) as ExecutionProcess[]}
              onSelectTask={handleSelectTask}
              onRunPhase={handleRunPhaseRole}
              issueTitle={currentIssue?.title}
              onDeleteIssue={() => {
                if (currentIssue) {
                  return handleDeleteIssue(currentIssue.id);
                }
              }}
            />
          </div>
        )}
      </main>

      {/* Task Execution Sheet (Opened when a task is selected from the board) */}
      <Sheet open={!!currentTaskId} onOpenChange={(open) => !open && setCurrentTaskId(null)}>
        <SheetContent side="right" className="w-[90vw] sm:max-w-[1400px] h-full p-0 flex flex-col gap-0 border-l border-border-subtle bg-surface shadow-2xl overflow-hidden">
          {currentTaskId && tasks.find(t => t.id === currentTaskId) && (
            <div className="flex flex-1 min-h-0 overflow-hidden">
              {/* Task Detail / Requirements Section */}
              <div className="flex-1 min-w-0 bg-background flex flex-col border-r border-border-subtle overflow-hidden">
                <div className="p-8 border-b border-border-subtle bg-surface/30">
                  <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className="size-10 rounded-xl bg-brand/10 flex items-center justify-center">
                        <Terminal size={20} className="text-brand" />
                      </div>
                      <div>
                        <h2 className="text-xl font-black tracking-tight text-foreground">
                          {tasks.find(t => t.id === currentTaskId)?.title}
                        </h2>
                        <p className="text-[10px] uppercase tracking-widest font-bold text-text-muted">{t("task.executionContext")}</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="px-3 py-1 rounded-lg bg-surface-raised border border-border-subtle text-[10px] font-black uppercase tracking-widest text-text-secondary">
                      {t("task.role")}: {tasks.find(t => t.id === currentTaskId)?.role.replace('_', ' ')}
                    </div>
                    <div className="px-3 py-1 rounded-lg bg-surface-raised border border-border-subtle text-[10px] font-black uppercase tracking-widest text-text-secondary">
                      {t("task.phase")}: {tasks.find(t => t.id === currentTaskId)?.phase}
                    </div>
                    <div className="px-3 py-1 rounded-lg bg-surface-raised border border-border-subtle text-[10px] font-black uppercase tracking-widest text-text-secondary">
                      {t("task.executor")}: {tasks.find(t => t.id === currentTaskId)?.executor}
                    </div>
                  </div>
                </div>
                
                <div className="flex-1 overflow-y-auto p-8">
                  <div className="prose prose-invert max-w-none">
                    <h3 className="text-sm font-black uppercase tracking-widest text-brand mb-4">{t("task.issueObjective")}</h3>
                    <p className="text-sm text-text-secondary leading-relaxed mb-10">
                      {currentIssue?.description || t("task.noDescription")}
                    </p>

                    <h3 className="text-sm font-black uppercase tracking-widest text-brand mb-4">{t("task.contextualArtifacts")}</h3>
                    <ArtifactPanel artifacts={artifacts} />
                  </div>
                </div>
              </div>

              {/* Execution Sidebar Section (Coordination / Logs) */}
              <div className="w-[500px] shrink-0 flex flex-col bg-surface overflow-hidden">
                <Tabs defaultValue="run-detail" className="flex flex-col h-full overflow-hidden">
                  <div className="px-6 border-b border-border-subtle bg-surface/50 shrink-0">
                    <TabsList className="bg-transparent h-14 w-full justify-start gap-8 p-0">
                      <TabsTrigger
                        value="run-detail"
                        className="data-[state=active]:bg-transparent data-[state=active]:text-brand relative h-full rounded-none border-b-2 border-transparent data-[state=active]:border-brand px-0 text-[10.5px] font-black uppercase tracking-[0.2em] transition-all"
                      >
                        {t("run.console")}
                      </TabsTrigger>
                      <TabsTrigger
                        value="coordination"
                        className="data-[state=active]:bg-transparent data-[state=active]:text-brand relative h-full rounded-none border-b-2 border-transparent data-[state=active]:border-brand px-0 text-[10.5px] font-black uppercase tracking-[0.2em] transition-all"
                      >
                        {t("agents.title")}
                      </TabsTrigger>
                    </TabsList>
                  </div>

                  <div className="flex-1 min-h-0">
                    <TabsContent value="run-detail" className="h-full m-0 flex flex-col">
                      <RunDetail
                        process={selectedProcess ?? null}
                        isLoadingProcess={isLoadingProcess}
                        taskMeta={currentTask}
                        task={displayedProcessMessages}
                        logs={displayedProcessLogs}
                        isLoadingLogs={isLoadingLogs && displayedProcessLogs.length === 0}
                        isLoadingMessages={isLoadingMessages && displayedProcessMessages.length === 0}
                        onSubmitForReview={handleTaskSubmitForReview}
                        onReview={handleTaskReview}
                        onRunInitial={async (executor, provider, model) => {
                          if (!currentTask) return;
                          try {
                            await updateCodexTask(currentTask.id, executor, provider, model);
                            const newProcess = await runCodexTask(currentTask.id, { executor, provider, model });
                            setSelectedProcessId(newProcess.id);
                            if (currentWorkspaceId) {
                              await loadWorkspaceData(currentWorkspaceId);
                            }
                          } catch (err) {
                            setError(err instanceof Error ? err.message : "Failed to run task");
                          }
                        }}
                        onRunAgain={async (executor, provider, model) => {
                          if (selectedProcess) {
                            try {
                              const result = await rerunCodexTask(selectedProcess.task_id, { executor, provider, model });
                              if (result.execution_process?.id) {
                                setOptimisticProcess(result.execution_process as ExecutionProcess);
                                setSelectedProcessId(result.execution_process.id);
                              }
                              // WS workspace stream will sync task / EP status updates.
                              // No full reload, avoids re-mount flicker.
                            } catch (err) {
                              setError(err instanceof Error ? err.message : "Failed to rerun task");
                              addToast({ type: "error", title: "重跑失败", message: err instanceof Error ? err.message : undefined });
                            }
                          }
                        }}
                        onDelete={async () => {
                          if (selectedProcess) {
                            try {
                              await deleteCodexTask(selectedProcess.task_id);
                              setSelectedProcessId(null);
                              if (currentWorkspaceId) await loadWorkspaceData(currentWorkspaceId);
                            } catch (err) {
                              setError(err instanceof Error ? err.message : "Failed to delete task");
                            }
                          }
                        }}
                        onSendMessage={handleSendMessage}
                        allTasks={tasks}
                        catalog={runtimeCatalog}
                        showTransitionToArchitecture={currentIssue?.current_phase === "requirements"}
                        canTransitionToArchitecture={
                          currentIssue?.current_phase === "requirements" &&
                          !hasActiveIssueTask &&
                          isPmTaskDone &&
                          !isTransitioningToArchitecture
                        }
                        isTransitioningToArchitecture={isTransitioningToArchitecture}
                        onTransitionToArchitecture={handleTransitionToArchitecture}
                        showTransitionToDevelopment={currentIssue?.current_phase === "architecture" || currentIssue?.current_phase === "development"}
                        canTransitionToDevelopment={
                          (currentIssue?.current_phase === "architecture" || currentIssue?.current_phase === "development") &&
                          !hasActiveIssueTask &&
                          hasArchitectureArtifacts &&
                          !isTransitioningToDevelopment
                        }
                        isTransitioningToDevelopment={isTransitioningToDevelopment}
                        onTransitionToDevelopment={handleTransitionToDevelopment}
                        showTransitionToTesting={currentIssue?.current_phase === "development" || currentIssue?.current_phase === "testing"}
                        canTransitionToTesting={
                          (currentIssue?.current_phase === "development" || currentIssue?.current_phase === "testing") &&
                          !hasActiveIssueTask &&
                          allEngineerTasksDone &&
                          !isTransitioningToTesting
                        }
                        isTransitioningToTesting={isTransitioningToTesting}
                        onTransitionToTesting={handleTransitionToTesting}
                        qaReportStatus={qaReportStatus}
                        lastResolvedMode={lastResolvedMode}
                        onTerminate={async () => {
                          if (currentTaskId) {
                            try {
                              await terminateCodexTask(currentTaskId);
                              if (currentWorkspaceId) await loadWorkspaceData(currentWorkspaceId);
                            } catch (err) {
                              setError(err instanceof Error ? err.message : "Failed to terminate task");
                            }
                          } else if (selectedProcess) {
                            try {
                              await terminateCodexTask(selectedProcess.task_id);
                              if (currentWorkspaceId) await loadWorkspaceData(currentWorkspaceId);
                            } catch (err) {
                              setError(err instanceof Error ? err.message : "Failed to terminate task");
                            }
                          }
                        }}
                      />
                    </TabsContent>

                    <TabsContent value="coordination" className="h-full m-0 flex flex-col">
                      <AgentCoordinationPanel
                        tasks={tasks.filter(t => t.id === currentTaskId)}
                        helpRequests={helpRequests.filter(h => h.parent_task_id === currentTaskId)}
                        executionProcesses={Object.values(executionProcessesAll).filter(p => (p as ExecutionProcess).task_id === currentTaskId) as ExecutionProcess[]}
                        onSelectTask={handleSelectTask}
                        onSelectProcess={setSelectedProcessId}
                      />
                    </TabsContent>
                  </div>
                </Tabs>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>

      {pendingApprovals.length > 0 && (
        <ApprovalDialog
          approval={pendingApprovals[0]}
          onResolve={(decision, feedback) =>
            handleResolveApproval(pendingApprovals[0].id, decision, feedback)
          }
          onClose={() => setPendingApprovals((prev) => prev.slice(1))}
        />
      )}

      <CommandPalette
        onCreateIssue={() => {}}
        onCreateWorkspace={() => {}}
      />

      <MacroRecorder
        open={macroRecorderOpen}
        onOpenChange={setMacroRecorderOpen}
      />

      <KeyboardShortcutsModal />

    </div>
  );
}

export default function WorkbenchPage() {
  const [currentWorkspaceId, setCurrentWorkspaceId] = useState<string | null>(null);

  return (
    <ExecutionProcessesProvider workspaceId={currentWorkspaceId}>
      <WorkbenchInner
        currentWorkspaceId={currentWorkspaceId}
        onWorkspaceChange={setCurrentWorkspaceId}
      />
    </ExecutionProcessesProvider>
  );
}
