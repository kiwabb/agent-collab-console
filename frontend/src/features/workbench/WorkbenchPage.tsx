"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
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
  createCodexIssue,
  deleteCodexIssue,
  createCodexTask,
  runCodexTask,
  deleteCodexTask,
  sendCodexTaskMessage,
  continueCodexTask,
  getExecutionProcessLogs,
  getExecutionProcessMessages,
  getPendingApprovals,
  resolveApproval,
  getTaskHelpRequests,
  getExecutionProcesses,
  submitCodexTask,
  reviewCodexTask,
  terminateCodexTask,
  updateCodexTaskExecutor,
} from "@/lib/api";
import { ExecutionProcessesProvider } from "@/providers/ExecutionProcessesProvider";
import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";
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
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useTheme, type ThemePreference } from "@/providers/ThemeProvider";
import { useI18n } from "@/providers/I18nProvider";
import type { Locale } from "@/lib/i18n";
import {
  Activity,
  RotateCcw,
  ChevronRight,
  Home,
  Layout,
  MessageSquare,
  Settings,
  Bell,
  Check,
  Languages,
  Moon,
  Sun,
  Monitor,
  Terminal,
  AlertCircle,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { createIssueAndInitialTask } from "@/features/workbench/workbenchActions";

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
  const [selectedProcessSnapshot, setSelectedProcessSnapshot] = useState<ExecutionProcess | null>(null);
  const [processLogs, setProcessLogs] = useState<LogEvent[]>([]);
  const [processMessages, setProcessMessages] = useState<CodexTaskMessage[]>([]);
  const [helpRequests, setHelpRequests] = useState<HelpRequest[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isTransitioningToArchitecture, setIsTransitioningToArchitecture] = useState(false);
  const [isTransitioningToDevelopment, setIsTransitioningToDevelopment] = useState(false);
  const [isLoadingLogs, setIsLoadingLogs] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedExecutor, setSelectedExecutor] = useState<"codex" | "claude">("codex");

  const { executionProcessesAll, isConnected, lastEvent } = useExecutionProcessesContext();
  const { theme, resolvedTheme, setTheme } = useTheme();
  const { locale, setLocale, t } = useI18n();

  const currentWorkspace = workspaces.find(w => w.id === currentWorkspaceId);
  const currentIssue = issues.find((i) => i.id === currentIssueId) ?? null;
  async function handleTaskSubmitForReview() {
    if (!currentTaskId) return;
    try {
      const updated = await submitCodexTask(currentTaskId);
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      if (currentWorkspaceId) {
        await loadWorkspaceData(currentWorkspaceId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit task for review");
    }
  }

  async function handleTaskReview(decision: "approve" | "reject", comment: string) {
    if (!currentTaskId) return;
    try {
      const updated = await reviewCodexTask(currentTaskId, decision, comment);
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit review");
    }
  }

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
  
  const hasActiveIssueTask = currentTasks.some((task) => {
    return isTaskRuntimeActive(task, Object.values(executionProcessesAll) as ExecutionProcess[]);
  });
  const transitionToArchitectureDisabledReason = hasActiveIssueTask
    ? t("task.running")
    : isPmTaskDone
      ? null
      : t("issue.transition.requiresArtifacts");
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
    ? ((Object.values(executionProcessesAll) as ExecutionProcess[]).find(
        (p) => p.id === selectedProcessId,
      ) ?? (selectedProcessSnapshot?.id === selectedProcessId ? selectedProcessSnapshot : null))
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

  const loadWorkspaceData = useCallback(async (workspaceId: string) => {
    try {
      const [iss, tks] = await Promise.all([
        getCodexIssues(workspaceId),
        getCodexTasks(workspaceId, null),
      ]);
      setIssues(iss);
      setTasks(tks);
      const hrs: HelpRequest[] = [];
      for (const task of tks) {
        try {
          const reqs = await getTaskHelpRequests(task.id);
          hrs.push(...reqs);
        } catch {}
      }
      setHelpRequests(hrs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workspace data");
    }
  }, []);

  useEffect(() => {
    getWorkspaces()
      .then(setWorkspaces)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!currentWorkspaceId) {
      setView("home");
      return;
    }
    loadWorkspaceData(currentWorkspaceId);
  }, [currentWorkspaceId, loadWorkspaceData]);

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

    if (lastEvent.type === "task_status") {
      setTasks((prev) =>
        prev.map((t) =>
          t.id === lastEvent.task_id
            ? { ...t, status: lastEvent.status, review_comment: lastEvent.review_comment }
            : t
        )
      );
    } else if (lastEvent.type === "task_created") {
      setTasks((prev) => {
        if (prev.some((t) => t.id === lastEvent.task.id)) return prev;
        return [...prev, lastEvent.task];
      });
    }
  }, [lastEvent]);

  useEffect(() => {
    if (!selectedProcessId) {
      setIsLoadingLogs(false);
      setIsLoadingMessages(false);
      setProcessLogs([]);
      setProcessMessages([]);
      setSelectedProcessSnapshot(null);
      return;
    }
    let cancelled = false;
    setIsLoadingLogs(true);
    setIsLoadingMessages(true);
    Promise.all([
      getExecutionProcessLogs(selectedProcessId),
      getExecutionProcessMessages(selectedProcessId),
    ])
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
      setError(err instanceof Error ? err.message : "Failed to create workspace");
    }
  }

  function handleSelectWorkspace(id: string) {
    onWorkspaceChange(id);
    setView("workspace");
    setCurrentIssueId(null);
    setCurrentTaskId(null);
    setSelectedProcessId(null);
    setSelectedProcessSnapshot(null);
  }

  async function handleDeleteWorkspace(id: string) {
    try {
      await deleteWorkspace(id);
      setWorkspaces((prev) => prev.filter((w) => w.id !== id));
      if (currentWorkspaceId === id) {
        onWorkspaceChange(null);
        setView("home");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete workspace");
    }
  }

  async function handleCreateIssue(title: string, description: string, executor: "codex" | "claude") {
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
      });
      setIssues((prev) => [...prev, issue]);
      setTasks((prev) => [...prev, initialTask]);
      handleSelectIssue(issue.id);
      setSelectedProcessId(executionProcess.id);
      setSelectedProcessSnapshot(executionProcess);
      setCurrentTaskId(initialTask.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create issue");
    }
  }

  function handleSelectIssue(id: string) {
    setCurrentIssueId(id);
    setView("issue");
    setCurrentTaskId(null);
  }

  function handleSelectTask(id: string) {
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

    if (task?.executor === "codex" || task?.executor === "claude") {
      setSelectedExecutor(task.executor);
    }

    setCurrentTaskId(id);
  }

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
        setSelectedProcessSnapshot(null);
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

  async function handleTransitionToArchitecture() {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to transition issue to architecture");
    } finally {
      setIsTransitioningToArchitecture(false);
    }
  }

  async function handleTransitionToDevelopment() {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to transition issue to development");
    } finally {
      setIsTransitioningToDevelopment(false);
    }
  }

  async function handleRunPhaseRole(phase: string, executor: "codex" | "claude") {
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
      );
      setTasks((prev) => [...prev, task]);
      const executionProcess = await runCodexTask(task.id);
      setSelectedProcessId(executionProcess.id);
      setSelectedProcessSnapshot(executionProcess);
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

  async function handleSendMessage(content: string) {
    if (!selectedProcess) return;
    try {
      await sendCodexTaskMessage(selectedProcess.task_id, content);
      const msgs = await getExecutionProcessMessages(selectedProcess.id);
      setProcessMessages(msgs);
    } catch {}
  }

  const themeOptions: { value: ThemePreference; label: string; icon: React.ReactNode }[] = [
    { value: "light", label: t("settings.theme.light"), icon: <Sun size={14} /> },
    { value: "dark", label: t("settings.theme.dark"), icon: <Moon size={14} /> },
    { value: "system", label: t("settings.theme.system"), icon: <Monitor size={14} /> },
  ];

  const localeOptions: { value: Locale; label: string }[] = [
    { value: "zh-CN", label: t("settings.language.zh") },
    { value: "en-US", label: t("settings.language.en") },
  ];

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
            
            {currentWorkspaceId && (
              <>
                <ChevronRight size={14} className="text-text-muted/40" />
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
              </>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-4 text-text-muted">
            <Bell size={18} className="hover:text-foreground cursor-pointer transition-colors" />
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button 
                  className="p-1.5 rounded-md hover:bg-surface-hover text-text-muted hover:text-foreground transition-colors cursor-pointer outline-none" 
                  aria-label={t("settings.title")} 
                  title={t("settings.title")}
                >
                  <Settings size={18} />
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content 
                  align="end" 
                  sideOffset={8}
                  className="w-56 bg-surface-raised border border-border-subtle rounded-xl shadow-2xl p-1.5 z-[100] animate-in fade-in zoom-in-95 duration-200"
                >
                  <DropdownMenu.Label className="px-3 py-2 text-[10px] font-black uppercase tracking-widest text-text-muted">
                    {t("settings.theme")}
                  </DropdownMenu.Label>
                  {themeOptions.map((option) => (
                    <DropdownMenu.Item 
                      key={option.value} 
                      onClick={() => setTheme(option.value)}
                      className="flex items-center gap-3 px-3 py-2 text-xs font-bold rounded-lg cursor-pointer outline-none hover:bg-surface-hover hover:text-brand transition-colors"
                    >
                      {option.icon}
                      <span>{option.label}</span>
                      {theme === option.value && <Check size={14} className="ml-auto text-brand" />}
                    </DropdownMenu.Item>
                  ))}
                  
                  <div className="h-px bg-border-subtle my-1.5 mx-1" />
                  
                  <DropdownMenu.Label className="px-3 py-2 text-[10px] font-black uppercase tracking-widest text-text-muted">
                    {t("settings.language")}
                  </DropdownMenu.Label>
                  {localeOptions.map((option) => (
                    <DropdownMenu.Item 
                      key={option.value} 
                      onClick={() => setLocale(option.value)}
                      className="flex items-center gap-3 px-3 py-2 text-xs font-bold rounded-lg cursor-pointer outline-none hover:bg-surface-hover hover:text-brand transition-colors"
                    >
                      <Languages size={14} />
                      <span>{option.label}</span>
                      {locale === option.value && <Check size={14} className="ml-auto text-brand" />}
                    </DropdownMenu.Item>
                  ))}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
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
          <div className="mx-8 mt-6 p-4 rounded-xl bg-error/10 border border-error/20 flex items-center justify-between animate-in slide-in-from-top-4 duration-300">
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
            <button 
              onClick={() => setError(null)}
              className="p-2 hover:bg-error/10 rounded-lg text-error/60 hover:text-error transition-all"
            >
              <RotateCcw size={14} className="rotate-45" />
            </button>
          </div>
        )}

        {view === "home" && (
          <div className="h-full overflow-y-auto no-scrollbar">
            <WorkspaceGrid
              workspaces={workspaces}
              onSelect={handleSelectWorkspace}
              onCreate={handleCreateWorkspace}
              onDelete={handleDeleteWorkspace}
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
                        taskMeta={currentTask}
                        task={displayedProcessMessages}
                        logs={displayedProcessLogs}
                        isLoadingLogs={isLoadingLogs && displayedProcessLogs.length === 0}
                        isLoadingMessages={isLoadingMessages && displayedProcessMessages.length === 0}
                        onSubmitForReview={handleTaskSubmitForReview}
                        onReview={handleTaskReview}
                        onRunInitial={async (executor) => {
                          if (!currentTask) return;
                          try {
                            if (executor !== currentTask.executor) {
                              await updateCodexTaskExecutor(currentTask.id, executor);
                            }
                            const newProcess = await runCodexTask(currentTask.id);
                            setSelectedProcessId(newProcess.id);
                            setSelectedProcessSnapshot(newProcess);
                            if (currentWorkspaceId) {
                              await loadWorkspaceData(currentWorkspaceId);
                            }
                          } catch (err) {
                            setError(err instanceof Error ? err.message : "Failed to run task");
                          }
                        }}
                        onRunAgain={async (executor) => {
                          if (selectedProcess) {
                            try {
                              const currentTask = tasks.find(t => t.id === selectedProcess.task_id);
                              if (executor !== currentTask?.executor) {
                                await updateCodexTaskExecutor(selectedProcess.task_id, executor);
                              }
                              const newProcess = await runCodexTask(selectedProcess.task_id);
                              setSelectedProcessId(newProcess.id);
                              setSelectedProcessSnapshot(newProcess);
                            } catch (err) {
                              setError(err instanceof Error ? err.message : "Failed to rerun task");
                            }
                          }
                        }}
                        onDelete={async () => {
                          if (selectedProcess) {
                            try {
                              await deleteCodexTask(selectedProcess.task_id);
                              setSelectedProcessId(null);
                              setSelectedProcessSnapshot(null);
                              if (currentWorkspaceId) await loadWorkspaceData(currentWorkspaceId);
                            } catch (err) {
                              setError(err instanceof Error ? err.message : "Failed to delete task");
                            }
                          }
                        }}
                        onSendMessage={handleSendMessage}
                        allTasks={tasks}
                        selectedExecutor={selectedExecutor}
                        onExecutorChange={setSelectedExecutor}
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
