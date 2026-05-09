import type { CodexIssue, CodexTask, ExecutionProcess } from "@/lib/types";

type CreateCodexIssueFn = (workspaceId: string, title: string, description: string) => Promise<CodexIssue>;
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
}): Promise<{ issue: CodexIssue; initialTask: CodexTask; executionProcess: ExecutionProcess }> {
  const issue = await createCodexIssue(workspaceId, title, description);
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
  const processStatus = executionProcess.status.toLowerCase();
  const initialTask = {
    ...createdTask,
    last_execution_process_id: executionProcess.id,
    status: createdTask.status === "pending" ? processStatus : createdTask.status,
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
    await updateTask(taskId, selectedExecutor, selectedProvider, selectedModel);
  }
  return runTask(taskId, { executor: selectedExecutor, provider: selectedProvider, model: selectedModel });
}
