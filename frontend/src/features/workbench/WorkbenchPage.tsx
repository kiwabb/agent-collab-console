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
  transitionIssueToArchitecture,
  transitionIssueToDevelopment,
  transitionIssueToTesting,
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
import { useExecutionProcessesContext, isBusTaskStatusEvent, isBusTaskCreatedEvent } from "@/contexts/ExecutionProcessesContext";
import { WorkspaceGrid } from "@/features/workspaces/WorkspaceGrid";
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
import { createIssueAndInitialTask } from "@/features/workbench/workbenchActions";
import { KeyboardShortcutsModal } from "@/components/ui/keyboard-shortcuts-modal";
import { CommandPalette } from "@/components/ui/command-palette";
import { MacroRecorder, useMacros } from "@/components/ui/macro-recorder";
import { PresenceIndicator } from "@/components/ui/presence-indicator";

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

  const { isConnected, lastEvent, executionProcessesAll } = useExecutionProcessesContext();
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
  const selectedProcess = selectedProcessId
    ? (Object.values(executionProcessesAll) as ExecutionProcess[]).find(
        (p) => p.id === selectedProcessId,
      ) ?? null
    : null;
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
    setIsLoadingWorkspaces(true);
    getWorkspaces()
      .then(setWorkspaces)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoadingWorkspaces(false));
  }, []);

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
    }
  }, [lastEvent]);

  useEffect(() => {
    if (!selectedProcessId) {
      setIsLoadingLogs(false);
      setIsLoadingMessages(false);
      setProcessLogs([]);
      setProcessMessages([]);
      return;
    }
    let cancelled = false;
    setIsLoadingLogs(true);
    setIsLoadingMessages(true);
    setIsLoadingProcess(true);
    // Logs are EP-scoped; messages are task-scoped so chat history persists
    // across re-runs / follow-up runs that spawn new execution processes.
    const selectedEp = (Object.values(executionProcessesAll) as ExecutionProcess[]).find(
      (p) => p.id === selectedProcessId,
    );
    const messagesPromise = selectedEp?.task_id
      ? getCodexTaskMessages(selectedEp.task_id)
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
  }, [selectedProcessId]);

  useEffect(() => {
    getPendingApprovals()
      .then((res) => setPendingApprovals(res.pending))
      .catch(() => setPendingApprovals([]));
  }, []);

  async function handleCreateWorkspace(title: string) {
    try {
      const ws = await createWorkspace(title);
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
    model: string | null
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

  const handleTransitionToArchitecture = useCallback(async () => {
    if (!currentIssue) return;
    setIsTransitioningToArchitecture(true);
    try {
      const result = await transitionIssueToArchitecture(currentIssue.id);
      setIssues((prev) => prev.map((issue) => (issue.id === result.issue.id ? result.issue : issue)));
      const architectureTask = result.task;
      if (architectureTask) {
        setTasks((prev) => {
          const exists = prev.some((task) => task.id === architectureTask.id);
          if (exists) {
            return prev.map((task) => (task.id === architectureTask.id ? architectureTask : task));
          }
          return [...prev, architectureTask];
        });
      }
      const freshArtifacts = await getCodexIssueArtifacts(currentIssue.id);
      setArtifacts(freshArtifacts);
      addToast({ type: "success", title: "Transitioned to Architecture" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to transition issue to architecture";
      setError(msg);
      addToast({ type: "error", title: "Failed to transition", message: msg });
    } finally {
      setIsTransitioningToArchitecture(false);
    }
  }, [currentIssue]);

  const handleTransitionToDevelopment = useCallback(async () => {
    if (!currentIssue) return;
    setIsTransitioningToDevelopment(true);
    try {
      const result = await transitionIssueToDevelopment(currentIssue.id);
      setIssues((prev) => prev.map((issue) => (issue.id === result.issue.id ? result.issue : issue)));
      setTasks((prev) => {
        const byId = new Map(prev.map((task) => [task.id, task]));
        for (const task of result.tasks) byId.set(task.id, task);
        return Array.from(byId.values());
      });
      const freshArtifacts = await getCodexIssueArtifacts(currentIssue.id);
      setArtifacts(freshArtifacts);
      addToast({ type: "success", title: "Transitioned to Development" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to transition issue to development";
      setError(msg);
      addToast({ type: "error", title: "Failed to transition", message: msg });
    } finally {
      setIsTransitioningToDevelopment(false);
    }
  }, [currentIssue]);

  const handleTransitionToTesting = useCallback(async () => {
    if (!currentIssue) return;
    setIsTransitioningToTesting(true);
    try {
      const result = await transitionIssueToTesting(currentIssue.id);
      setIssues((prev) => prev.map((issue) => (issue.id === result.issue.id ? result.issue : issue)));
      const qaTask = result.task;
      if (qaTask) {
        setTasks((prev) => {
          const exists = prev.some((task) => task.id === qaTask.id);
          if (exists) {
            return prev.map((task) => (task.id === qaTask.id ? qaTask : task));
          }
          return [...prev, qaTask];
        });
      }
      const freshArtifacts = await getCodexIssueArtifacts(currentIssue.id);
      setArtifacts(freshArtifacts);
      addToast({ type: "success", title: "已流转到测试阶段" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "流转到测试失败";
      setError(msg);
      addToast({ type: "error", title: "流转失败", message: msg });
    } finally {
      setIsTransitioningToTesting(false);
    }
  }, [currentIssue]);

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
        `${t(config.labelKey as any)} - ${currentIssue.title}`,
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
      // Backend creates a new execution process for every run. Switch UI to it
      // for log streaming, but fetch messages task-scoped so prior turns persist.
      const newProcess = result?.execution_process;
      if (newProcess?.id) {
        setSelectedProcessId(newProcess.id);
      }
      const msgs = await getCodexTaskMessages(selectedProcess.task_id);
      setProcessMessages(msgs);
      if (currentWorkspaceId) {
        await loadWorkspaceData(currentWorkspaceId);
      }
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
            <WorkspaceGrid
              workspaces={workspaces}
              onSelect={handleSelectWorkspace}
              onCreate={handleCreateWorkspace}
              onDelete={handleDeleteWorkspace}
              isLoading={isLoadingWorkspaces}
            />
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
              isLoading={isLoadingIssues}
            />
          </div>
        )}

        {view === "issue" && currentIssueId && (
          <div className="h-full overflow-hidden">
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
                                setSelectedProcessId(result.execution_process.id);
                              }
                              if (currentWorkspaceId) await loadWorkspaceData(currentWorkspaceId);
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
