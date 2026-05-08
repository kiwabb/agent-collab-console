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
) => Promise<CodexTask>;
type RunCodexTaskFn = (taskId: string) => Promise<ExecutionProcess>;
type UpdateExecutorFn = (taskId: string, executor: "codex" | "claude") => Promise<CodexTask>;

export async function createIssueAndInitialTask({
  workspaceId,
  title,
  description,
  executor,
  issueTitle,
  createCodexIssue,
  createCodexTask,
  runCodexTask,
}: {
  workspaceId: string;
  title: string;
  description: string;
  executor: "codex" | "claude";
  issueTitle: string;
  createCodexIssue: CreateCodexIssueFn;
  createCodexTask: CreateCodexTaskFn;
  runCodexTask: RunCodexTaskFn;
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
  );
  const executionProcess = await runCodexTask(createdTask.id);
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
  updateExecutor,
  runTask,
}: {
  taskId: string;
  selectedExecutor: "codex" | "claude";
  currentExecutor: "codex" | "claude";
  updateExecutor: UpdateExecutorFn;
  runTask: RunCodexTaskFn;
}): Promise<ExecutionProcess> {
  if (selectedExecutor !== currentExecutor) {
    await updateExecutor(taskId, selectedExecutor);
  }
  return runTask(taskId);
}
