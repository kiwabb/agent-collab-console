import type { CodexIssue, ExecutionProcess, WorkflowGraph } from "@/lib/types";

type CreateCodexIssueFn = (
  workspaceId: string,
  title: string,
  description: string,
  baseBranch?: string | null,
  executor?: string | null,
  provider?: string | null,
  model?: string | null,
) => Promise<CodexIssue>;
type AutoStartIssueGraphFn = (issueId: string) => Promise<WorkflowGraph>;
type RunCodexTaskFn = (taskId: string, overrides?: { executor?: string; provider?: string | null; model?: string | null }) => Promise<ExecutionProcess>;
type UpdateTaskFn = (taskId: string, executor?: string, provider?: string | null, model?: string | null) => Promise<import("@/lib/types").CodexTask>;

export async function createIssueAndInitialTask({
  workspaceId,
  title,
  description,
  createCodexIssue,
  autoStartIssueGraph,
  baseBranch,
  executor,
  provider,
  model,
}: {
  workspaceId: string;
  title: string;
  description: string;
  createCodexIssue: CreateCodexIssueFn;
  autoStartIssueGraph: AutoStartIssueGraphFn;
  baseBranch?: string | null;
  // Conductor executor selection — persisted on the issue and used by sub-agents.
  executor?: string;
  issueTitle?: string;
  provider?: string | null;
  model?: string | null;
}): Promise<{ issue: CodexIssue }> {
  const issue = await createCodexIssue(
    workspaceId,
    title,
    description,
    baseBranch ?? null,
    executor ?? null,
    provider ?? null,
    model ?? null,
  );
  await autoStartIssueGraph(issue.id);
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
      return await runTask(taskId, { executor: selectedExecutor, provider: selectedProvider, model: selectedModel });
    } catch (runError) {
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
