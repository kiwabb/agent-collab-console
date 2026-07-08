import { normalizeLogs } from "./codexLogNormalizer";
import type { CodexTaskMessage, ExecutionProcess, NormalizedEntry } from "./types";

type ProcessConversationFields = ExecutionProcess & {
  messages?: Record<string, CodexTaskMessage>;
  logs?: unknown[];
};

export function sortMessages<T extends { created_at?: string | null; role?: string }>(messages: T[]): T[] {
  return [...messages].sort((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
    if (aTime !== bTime) return aTime - bTime;
    if (a.role === b.role) return 0;
    if (a.role === "user") return -1;
    if (b.role === "user") return 1;
    return (a.role ?? "").localeCompare(b.role ?? "");
  });
}

export function sortLogs<T extends { created_at?: string | null }>(logs: T[]): T[] {
  return [...logs].sort((a, b) => {
    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime;
  });
}

export function mergeById<T extends { id?: string }>(items: T[] | undefined): T[] {
  const merged = new Map<string, T>();
  for (const item of items ?? []) {
    if (!item?.id) continue;
    merged.set(item.id, item);
  }
  return [...merged.values()];
}

export function mergeTaskConversationMessages(messageGroups: CodexTaskMessage[][]): CodexTaskMessage[] {
  return sortMessages(mergeById(messageGroups.flat()));
}

export function mergeTaskConversationLogs(logGroups: unknown[][]): unknown[] {
  return sortLogs(mergeById(logGroups.flat() as { id?: string; created_at?: string | null }[]));
}

export function buildConversationMessages(messages: CodexTaskMessage[], logs: unknown[]): CodexTaskMessage[] {
  const persistedMessages = mergeById(messages);
  const persistedAssistantKeys = new Set<string>();
  const persistedAssistantProcessIds = new Set<string>();
  for (const message of persistedMessages) {
    if (message.role !== "assistant" || typeof message.content !== "string") continue;
    persistedAssistantKeys.add(`${message.execution_process_id || "none"}::${message.content}`);
    if (message.execution_process_id) {
      persistedAssistantProcessIds.add(message.execution_process_id);
    }
  }

  const normalizedLogs = normalizeLogs(logs as Parameters<typeof normalizeLogs>[0]);
  const syntheticMessages: CodexTaskMessage[] = normalizedLogs
    .filter((entry: NormalizedEntry) => entry.type === "assistant" && typeof entry.content === "string" && entry.content)
    .filter((entry: NormalizedEntry) => !entry.executionProcessId || !persistedAssistantProcessIds.has(entry.executionProcessId))
    .filter((entry: NormalizedEntry) => !persistedAssistantKeys.has(`${entry.executionProcessId || "none"}::${entry.content}`))
    .map((entry: NormalizedEntry) => ({
      id: `logmsg-${entry.id}`,
      task_id: "",
      role: "assistant",
      content: entry.content || "",
      created_at: entry.timestamp || null,
      execution_process_id: entry.executionProcessId || null,
    }));

  return sortMessages(mergeById([...persistedMessages, ...syntheticMessages]));
}

export function buildTaskConversationDetail(
  taskMessages: CodexTaskMessage[],
  executionProcesses: ExecutionProcess[]
): { logs: unknown[]; messages: CodexTaskMessage[] } {
  const processMessages = executionProcesses.flatMap((process) =>
    Object.values((process as ProcessConversationFields).messages ?? {}),
  );
  const processLogs = executionProcesses.flatMap((process) => (process as ProcessConversationFields).logs ?? []);
  const logs = mergeTaskConversationLogs([processLogs]);
  return {
    logs,
    messages: buildConversationMessages([...taskMessages, ...(processMessages as CodexTaskMessage[])], logs),
  };
}
