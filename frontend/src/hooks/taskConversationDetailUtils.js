import { normalizeLogs } from "../utils/codexLogNormalizer.js";

export function sortMessages(messages) {
  return [...messages].sort((a, b) => {
    const aTime = a?.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b?.created_at ? new Date(b.created_at).getTime() : 0;
    if (aTime !== bTime) return aTime - bTime;
    if (a?.role === b?.role) return 0;
    if (a?.role === "user") return -1;
    if (b?.role === "user") return 1;
    return (a?.role || "").localeCompare(b?.role || "");
  });
}

export function sortLogs(logs) {
  return [...logs].sort((a, b) => {
    const aTime = a?.created_at ? new Date(a.created_at).getTime() : 0;
    const bTime = b?.created_at ? new Date(b.created_at).getTime() : 0;
    return aTime - bTime;
  });
}

export function mergeById(items) {
  const merged = new Map();
  for (const item of items || []) {
    if (!item?.id) continue;
    merged.set(item.id, item);
  }
  return [...merged.values()];
}

export function mergeTaskConversationMessages(messageGroups) {
  return sortMessages(mergeById((messageGroups || []).flat()));
}

export function mergeTaskConversationLogs(logGroups) {
  return sortLogs(mergeById((logGroups || []).flat()));
}

export function buildConversationMessages(messages, logs) {
  const persistedMessages = mergeById(messages || []);
  const persistedAssistantKeys = new Set();
  const persistedAssistantProcessIds = new Set();
  for (const message of persistedMessages) {
    if (message?.role !== "assistant" || typeof message?.content !== "string") continue;
    persistedAssistantKeys.add(`${message.execution_process_id || "none"}::${message.content}`);
    if (message.execution_process_id) {
      persistedAssistantProcessIds.add(message.execution_process_id);
    }
  }

  const syntheticMessages = normalizeLogs(logs || [])
    .filter((entry) => entry?.type === "assistant" && typeof entry?.content === "string" && entry.content)
    .filter((entry) => !entry.executionProcessId || !persistedAssistantProcessIds.has(entry.executionProcessId))
    .filter((entry) => !persistedAssistantKeys.has(`${entry.executionProcessId || "none"}::${entry.content}`))
    .map((entry) => ({
      id: `logmsg-${entry.id}`,
      role: "assistant",
      content: entry.content,
      created_at: entry.timestamp || null,
      execution_process_id: entry.executionProcessId || null,
    }));

  return sortMessages(mergeById([...persistedMessages, ...syntheticMessages]));
}

export function buildTaskConversationDetail(taskMessages, executionProcesses) {
  const processMessages = (executionProcesses || []).flatMap((process) =>
    Object.values(process?.messages || {}),
  );
  const processLogs = (executionProcesses || []).flatMap((process) => process?.logs || []);
  const logs = mergeTaskConversationLogs([processLogs]);
  return {
    logs,
    messages: buildConversationMessages([...(taskMessages || []), ...processMessages], logs),
  };
}
