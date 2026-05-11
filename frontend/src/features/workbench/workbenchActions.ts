import type { CodexIssue, CodexTask, ExecutionProcess } from "@/lib/types";

type CreateCodexIssueFn = (
  workspaceId: string,
  title: string,
  description: string,
  baseBranch?: string | null,
) => Promise<CodexIssue>;
type CreateCodexTaskFn = (
  sessionId: string,
  title: string,
  prompt: string,
  parentTaskId: string | null,
  executor: "codex" | "claude",
  role: string,
  issueId: string | null,
  phase: string,
  provider?: string | null,
  model?: string | null,
) => Promise<CodexTask>;
type RunCodexTaskFn = (taskId: string, overrides?: { executor?: "codex" | "claude"; provider?: string | null; model?: string | null }) => Promise<ExecutionProcess>;
type UpdateTaskFn = (taskId: string, executor?: "codex" | "claude", provider?: string | null, model?: string | null) => Promise<CodexTask>;

export async function createIssueAndInitialTask({
  workspaceId,
  title,
  description,
  executor,
  issueTitle,
  createCodexIssue,
  createCodexTask,
  runCodexTask,
  provider,
  model,
  baseBranch,
}: {
  workspaceId: string;
  title: string;
  description: string;
  executor: "codex" | "claude";
  issueTitle: string;
  createCodexIssue: CreateCodexIssueFn;
  createCodexTask: CreateCodexTaskFn;
  runCodexTask: RunCodexTaskFn;
  provider?: string | null;
  model?: string | null;
  baseBranch?: string | null;
}): Promise<{ issue: CodexIssue; initialTask: CodexTask; executionProcess: ExecutionProcess }> {
  const issue = await createCodexIssue(workspaceId, title, description, baseBranch ?? null);
  const createdTask = await createCodexTask(
    workspaceId,
    issueTitle,
    description || title,
    null,
    executor,
    "product_manager",
    issue.id,
    "requirements",
    provider,
    model,
  );
  const executionProcess = await runCodexTask(createdTask.id, { executor, provider, model });
  const initialTask = {
    ...createdTask,
    last_execution_process_id: executionProcess.id,
    status: executionProcess.status.toLowerCase(),
  };
  return { issue, initialTask, executionProcess };
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
  selectedExecutor: "codex" | "claude";
  currentExecutor: "codex" | "claude";
  selectedProvider: string | null;
  currentProvider: string | null;
  selectedModel: string | null;
  currentModel: string | null;
  updateTask: UpdateTaskFn;
  runTask: RunCodexTaskFn;
}): Promise<ExecutionProcess> {
  // Check if anything changed
  const needsUpdate =
    selectedExecutor !== currentExecutor ||
    selectedProvider !== currentProvider ||
    selectedModel !== currentModel;

  if (needsUpdate) {
    // Capture previous values for rollback on failure
    const previousExecutor = currentExecutor;
    const previousProvider = currentProvider;
    const previousModel = currentModel;

    try {
      await updateTask(taskId, selectedExecutor, selectedProvider, selectedModel);
    } catch (updateError) {
      // Revert to previous values if update succeeded but runTask fails
      // The update was already persisted, but we need to revert on runTask failure
      throw updateError;
    }

    try {
      return await runTask(taskId, { executor: selectedExecutor, provider: selectedProvider, model: selectedModel });
    } catch (runError) {
      // Revert executor/provider/model on runTask failure
      try {
        await updateTask(taskId, previousExecutor, previousProvider, previousModel);
      } catch (revertError) {
        console.error("Failed to revert task executor after runTask failure:", revertError);
      }
      throw runError;
    }
  }
  return runTask(taskId, { executor: selectedExecutor, provider: selectedProvider, model: selectedModel });
}
