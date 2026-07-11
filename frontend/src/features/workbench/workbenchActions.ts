import type { CodexIssue, CodexTask, ExecutionProcess, WorkflowGraph } from "@/lib/types";

type CreateCodexIssueFn = (
  workspaceId: string,
  title: string,
  description: string,
  baseBranch?: string | null,
  executor?: string | null,
  provider?: string | null,
  model?: string | null,
  acceptanceCriteria?: string[],
  acceptanceCriteriaConfirmed?: boolean,
) => Promise<CodexIssue>;
type AutoStartIssueGraphFn = (issueId: string) => Promise<WorkflowGraph>;
type CreateCodexTaskFn = (
  sessionId: string,
  title: string,
  prompt: string,
  parentTaskId?: string | null,
  executor?: string,
  role?: string,
  issueId?: string | null,
  phase?: string,
  provider?: string | null,
  model?: string | null,
) => Promise<CodexTask>;
type RunCodexTaskFn = (
  taskId: string,
  overrides?: {
    executor?: string | undefined;
    provider?: string | null | undefined;
    model?: string | null | undefined;
  },
) => Promise<ExecutionProcess>;
type UpdateTaskFn = (
  taskId: string,
  executor?: string,
  provider?: string | null,
  model?: string | null,
) => Promise<CodexTask>;

export async function createIssueAndInitialTask({
  workspaceId,
  title,
  description,
  createCodexIssue,
  createCodexTask,
  autoStartIssueGraph,
  runCodexTask,
  baseBranch,
  executor,
  issueTitle,
  provider,
  model,
  acceptanceCriteria,
  acceptanceCriteriaConfirmed,
}: {
  workspaceId: string;
  title: string;
  description: string;
  createCodexIssue: CreateCodexIssueFn;
  createCodexTask?: CreateCodexTaskFn;
  autoStartIssueGraph?: AutoStartIssueGraphFn;
  runCodexTask?: RunCodexTaskFn;
  baseBranch?: string | null | undefined;
  // Conductor executor selection — persisted on the issue and used by sub-agents.
  executor?: string | undefined;
  issueTitle?: string | undefined;
  provider?: string | null | undefined;
  model?: string | null | undefined;
  acceptanceCriteria?: string[] | undefined;
  acceptanceCriteriaConfirmed?: boolean | undefined;
}): Promise<{
  issue: CodexIssue;
  initialTask?: CodexTask;
  executionProcess?: ExecutionProcess;
}> {
  const issue = await createCodexIssue(
    workspaceId,
    title,
    description,
    baseBranch ?? null,
    executor ?? null,
    provider ?? null,
    model ?? null,
    acceptanceCriteria ?? [],
    acceptanceCriteriaConfirmed ?? false,
  );
  if (createCodexTask && runCodexTask) {
    const initialTask = await createCodexTask(
      workspaceId,
      issueTitle ?? title,
      description,
      null,
      executor ?? "codex",
      "product_manager",
      issue.id,
      "requirements",
      provider ?? null,
      model ?? null,
    );
    const executionProcess = await runCodexTask(initialTask.id, {
      executor,
      provider,
      model,
    });
    return { issue, initialTask, executionProcess };
  }
  if (autoStartIssueGraph) {
    await autoStartIssueGraph(issue.id);
  }
  return { issue };
}

export async function runCodexTaskWithExecutor({
  taskId,
  selectedExecutor,
  currentExecutor,
  selectedProvider,
  currentProvider,
  selectedModel,
  currentModel,
  updateTask,
  runTask,
}: {
  taskId: string;
  selectedExecutor: string;
  currentExecutor: string;
  selectedProvider: string | null;
  currentProvider: string | null;
  selectedModel: string | null;
  currentModel: string | null;
  updateTask: UpdateTaskFn;
  runTask: RunCodexTaskFn;
}): Promise<ExecutionProcess> {
  const needsUpdate =
    selectedExecutor !== currentExecutor ||
    selectedProvider !== currentProvider ||
    selectedModel !== currentModel;

  if (needsUpdate) {
    const previousExecutor = currentExecutor;
    const previousProvider = currentProvider;
    const previousModel = currentModel;

    try {
      await updateTask(taskId, selectedExecutor, selectedProvider, selectedModel);
    } catch (updateError) {
      throw updateError;
    }

    try {
      return await runTask(taskId, {
        executor: selectedExecutor,
        provider: selectedProvider,
        model: selectedModel,
      });
    } catch (runError) {
      try {
        await updateTask(taskId, previousExecutor, previousProvider, previousModel);
      } catch (revertError) {
        console.error("Failed to revert task executor after runTask failure:", revertError);
      }
      throw runError;
    }
  }
  return runTask(taskId, {
    executor: selectedExecutor,
    provider: selectedProvider,
    model: selectedModel,
  });
}
