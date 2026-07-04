"use client";

import type { Artifact, CodexTask, CodexTaskMessage, ExecutionProcess, HelpRequest, LogEvent } from "@/lib/types";
import { AgentCoordinationPanel } from "@/features/agents/AgentCoordinationPanel";
import { RunDetail } from "@/features/runs/RunDetail";
import { RunRecoveryPanel } from "@/features/runs/components/RunRecoveryPanel";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { useI18n } from "@/providers/I18nProvider";
import { useToast } from "@/components/ui/toast";
import { Terminal } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  deleteCodexTask,
  reviewCodexTask,
  rerunCodexTask,
  runCodexTask,
  submitCodexTask,
  terminateCodexTask,
  updateCodexTask,
} from "@/lib/api/tasks";
import { useWorkbenchStore, selectCurrentTask, selectCurrentIssue, selectSelectedProcess } from "@/store/workbenchStore";
import { useExecutionProcessesContext } from "@/contexts/ExecutionProcessesContext";
import { useMemo } from "react";
import {
  deriveRunRecoveryActions,
  type RecoveryAction,
} from "@/features/workbench/interaction/interactionState";

export function TaskExecutionSheet() {
  const { t } = useI18n();
  const { addToast } = useToast();

  const currentTaskId = useWorkbenchStore((s) => s.currentTaskId);
  const setCurrentTaskId = useWorkbenchStore((s) => s.setCurrentTaskId);
  const tasks = useWorkbenchStore((s) => s.tasks);
  const currentTask = useWorkbenchStore(selectCurrentTask);
  const currentIssue = useWorkbenchStore(selectCurrentIssue);
  const artifacts = useWorkbenchStore((s) => s.artifacts);
  const selectedProcess = useWorkbenchStore(selectSelectedProcess);
  const setSelectedProcessId = useWorkbenchStore((s) => s.setSelectedProcessId);

  const isLoadingProcess = useWorkbenchStore((s) => s.isLoadingProcess);
  const processLogs = useWorkbenchStore((s) => s.processLogs);
  const processMessages = useWorkbenchStore((s) => s.processMessages);
  const isLoadingLogs = useWorkbenchStore((s) => s.isLoadingLogs);
  const isLoadingMessages = useWorkbenchStore((s) => s.isLoadingMessages);
  const runtimeCatalog = useWorkbenchStore((s) => s.runtimeCatalog);
  const currentWorkspaceId = useWorkbenchStore((s) => s.currentWorkspaceId);
  const helpRequests = useWorkbenchStore((s) => s.helpRequests);

  const isTransitioningToArchitecture = useWorkbenchStore((s) => s.isTransitioningToArchitecture);
  const isTransitioningToDevelopment = useWorkbenchStore((s) => s.isTransitioningToDevelopment);
  const isTransitioningToTesting = useWorkbenchStore((s) => s.isTransitioningToTesting);

  const { executionProcessesAll } = useExecutionProcessesContext();

  // Get executor label from catalog
  const executorLabel = useMemo(() => {
    if (!runtimeCatalog || !currentTask?.executor) return currentTask?.executor ?? "";
    const executor = runtimeCatalog.executors.find((e) => e.id === currentTask.executor);
    return executor?.label ?? currentTask.executor;
  }, [runtimeCatalog, currentTask?.executor]);

  // Derived state
  const currentIssueTasks = useMemo(() =>
    currentIssue ? tasks.filter((t: CodexTask) => t.issue_id === currentIssue.id) : [],
    [currentIssue, tasks]
  );

  const hasActiveIssueTask = useMemo(() =>
    currentIssueTasks.some((task: CodexTask) => {
      const activeStatuses = ["running", "responding"];
      return activeStatuses.includes(task.status?.toLowerCase());
    }),
    [currentIssueTasks]
  );

  const isPmTaskDone = useMemo(() =>
    currentIssueTasks.find((t: CodexTask) => t.role === "product_manager")?.status === "done",
    [currentIssueTasks]
  );

  const hasArchitectureArtifacts = useMemo(() =>
    artifacts.some((a: Artifact) => a.name === "architect/system_design.json" || a.name === "architect/implementation_plan.json"),
    [artifacts]
  );

  const allEngineerTasksDone = useMemo(() => {
    const engineerTasks = currentIssueTasks.filter((t: CodexTask) => t.role === "engineer");
    return engineerTasks.length > 0 && engineerTasks.every((t: CodexTask) => t.status === "done");
  }, [currentIssueTasks]);

  const qaReportStatus = useMemo(() => {
    const qaPlan = artifacts.find((a: Artifact) => a.name === "qa/qa_plan.json");
    if (!qaPlan || typeof qaPlan.content !== "string") return null;
    try {
      const parsed = JSON.parse(qaPlan.content);
      return parsed?.status || null;
    } catch {
      return null;
    }
  }, [artifacts]);

  const liveProcessLogs = useMemo(
    () => selectedProcess?.logs ?? [],
    [selectedProcess?.logs],
  );
  const liveProcessMessages = useMemo(
    () =>
      selectedProcess?.messages ? Object.values(selectedProcess.messages) : [],
    [selectedProcess?.messages],
  );

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

  const recoveryActions = useMemo(
    () =>
      deriveRunRecoveryActions({
        task: currentTask,
        process: selectedProcess ?? null,
      }),
    [currentTask, selectedProcess],
  );

  const handleRecoveryAction = async (id: RecoveryAction["id"]) => {
    if (!currentTask) return;
    try {
      if (id === "open_logs") {
        return;
      }
      if (id === "rerun_same") {
        const result = await rerunCodexTask(currentTask.id, {
          executor: currentTask.executor,
          provider: currentTask.provider ?? undefined,
          model: currentTask.model ?? undefined,
        });
        if (result.execution_process?.id) {
          useWorkbenchStore
            .getState()
            .setOptimisticProcess(result.execution_process as ExecutionProcess);
          setSelectedProcessId(result.execution_process.id);
        }
        addToast({ type: "success", title: t("taskExecution.toast.rerunStarted") });
        return;
      }
      if (id === "change_executor") {
        addToast({
          type: "info",
          title: t("taskExecution.toast.chooseRuntime"),
          message: t("taskExecution.toast.chooseRuntimeHint"),
        });
        return;
      }
      if (id === "stop_run") {
        await terminateCodexTask(currentTask.id);
        addToast({ type: "success", title: t("taskExecution.toast.terminationRequested") });
        return;
      }
      if (id === "submit_review") {
        const updated = await submitCodexTask(currentTask.id);
        useWorkbenchStore.getState().updateTask(updated.id, updated);
        addToast({ type: "success", title: t("taskExecution.toast.submittedReview") });
      }
    } catch (err) {
      addToast({
        type: "error",
        title: t("taskExecution.toast.recoveryFailed"),
        message: err instanceof Error ? err.message : String(err),
      });
    }
  };

  if (!currentTaskId || !currentTask) return null;

  return (
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
                  {currentTask.title}
                </h2>
                <p className="text-[10px] uppercase tracking-widest font-bold text-text-muted">{t("task.executionContext")}</p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="px-3 py-1 rounded-lg bg-surface-raised border border-border-subtle text-[10px] font-black uppercase tracking-widest text-text-secondary">
              {t("task.role")}: {currentTask.role.replace('_', ' ')}
            </div>
            <div className="px-3 py-1 rounded-lg bg-surface-raised border border-border-subtle text-[10px] font-black uppercase tracking-widest text-text-secondary">
              {t("task.phase")}: {currentTask.phase}
            </div>
            <div className="px-3 py-1 rounded-lg bg-surface-raised border border-border-subtle text-[10px] font-black uppercase tracking-widest text-text-secondary">
              {t("task.executor")}: {executorLabel}
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
              <div className="px-4 pt-4">
                <RunRecoveryPanel
                  actions={recoveryActions}
                  onAction={(id) => {
                    void handleRecoveryAction(id);
                  }}
                />
              </div>
              <RunDetail
                process={selectedProcess ?? null}
                isLoadingProcess={isLoadingProcess}
                taskMeta={currentTask}
                task={displayedProcessMessages}
                logs={displayedProcessLogs}
                isLoadingLogs={isLoadingLogs && displayedProcessLogs.length === 0}
                isLoadingMessages={isLoadingMessages && displayedProcessMessages.length === 0}
                onSubmitForReview={async () => {
                  try {
                    const updated = await submitCodexTask(currentTaskId);
                    useWorkbenchStore.getState().updateTask(updated.id, updated);
                  } catch (err) {
                    addToast({
                      type: "error",
                      title: t("taskExecution.toast.submitFailed"),
                      message: err instanceof Error ? err.message : String(err),
                    });
                  }
                }}
                onReview={async (decision, comment) => {
                  try {
                    const updated = await reviewCodexTask(currentTaskId, decision, comment);
                    useWorkbenchStore.getState().updateTask(updated.id, updated);
                  } catch (err) {
                    addToast({
                      type: "error",
                      title: t("taskExecution.toast.reviewFailed"),
                      message: err instanceof Error ? err.message : String(err),
                    });
                  }
                }}
                onRunInitial={async (executor, provider, model) => {
                  try {
                    await updateCodexTask(currentTask.id, executor, provider, model);
                    const newProcess = await runCodexTask(currentTask.id, { executor, provider, model });
                    setSelectedProcessId(newProcess.id);
                    if (currentWorkspaceId) useWorkbenchStore.getState().setIsLoadingIssues(true);
                  } catch (err) {
                    addToast({
                      type: "error",
                      title: t("taskExecution.toast.runFailed"),
                      message: err instanceof Error ? err.message : String(err),
                    });
                  }
                }}
                onRunAgain={async (executor, provider, model) => {
                  if (selectedProcess) {
                    try {
                      const rerunResult = await rerunCodexTask(selectedProcess.task_id, { executor, provider, model });
                      if (rerunResult.execution_process?.id) {
                        useWorkbenchStore.getState().setOptimisticProcess(rerunResult.execution_process as ExecutionProcess);
                        setSelectedProcessId(rerunResult.execution_process.id);
                      }
                    } catch (err) {
                      addToast({
                        type: "error",
                        title: t("taskExecution.toast.rerunFailed"),
                        message: err instanceof Error ? err.message : String(err),
                      });
                    }
                  }
                }}
                onDelete={async () => {
                  if (selectedProcess) {
                    try {
                      await deleteCodexTask(selectedProcess.task_id);
                      setSelectedProcessId(null);
                    } catch (err) {
                      addToast({
                        type: "error",
                        title: t("taskExecution.toast.deleteFailed"),
                        message: err instanceof Error ? err.message : String(err),
                      });
                    }
                  }
                }}
                onSendMessage={async (content, mode) => {
                  try {
                    await useWorkbenchStore.getState().sendMessage(currentTaskId, content, mode);
                  } catch (err) {
                    addToast({
                      type: "error",
                      title: t("taskExecution.toast.sendFailed"),
                      message: err instanceof Error ? err.message : String(err),
                    });
                  }
                }}
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
                onTransitionToArchitecture={() => {
                  if (currentIssue) useWorkbenchStore.getState().transitionToArchitecture(currentIssue.id);
                }}
                showTransitionToDevelopment={currentIssue?.current_phase === "architecture" || currentIssue?.current_phase === "development"}
                canTransitionToDevelopment={
                  (currentIssue?.current_phase === "architecture" || currentIssue?.current_phase === "development") &&
                  !hasActiveIssueTask &&
                  hasArchitectureArtifacts &&
                  !isTransitioningToDevelopment
                }
                isTransitioningToDevelopment={isTransitioningToDevelopment}
                onTransitionToDevelopment={() => {
                  if (currentIssue) useWorkbenchStore.getState().transitionToDevelopment(currentIssue.id);
                }}
                showTransitionToTesting={currentIssue?.current_phase === "development" || currentIssue?.current_phase === "testing"}
                canTransitionToTesting={
                  (currentIssue?.current_phase === "development" || currentIssue?.current_phase === "testing") &&
                  !hasActiveIssueTask &&
                  allEngineerTasksDone &&
                  !isTransitioningToTesting
                }
                isTransitioningToTesting={isTransitioningToTesting}
                onTransitionToTesting={() => {
                  if (currentIssue) useWorkbenchStore.getState().transitionToTesting(currentIssue.id);
                }}
                qaReportStatus={qaReportStatus}
                lastResolvedMode={null}
                onTerminate={async () => {
                  try {
                    await terminateCodexTask(currentTaskId);
                  } catch (err) {
                    addToast({
                      type: "error",
                      title: t("taskExecution.toast.terminateFailed"),
                      message: err instanceof Error ? err.message : String(err),
                    });
                  }
                }}
              />
            </TabsContent>

            <TabsContent value="coordination" className="h-full m-0 flex flex-col">
              <AgentCoordinationPanel
                tasks={tasks.filter((t: CodexTask) => t.id === currentTaskId)}
                helpRequests={helpRequests.filter((h: HelpRequest) => h.parent_task_id === currentTaskId)}
                executionProcesses={Object.values(executionProcessesAll).filter((p: ExecutionProcess) => p.task_id === currentTaskId)}
                onSelectTask={(id) => setCurrentTaskId(id)}
                onSelectProcess={setSelectedProcessId}
              />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
