import type { NormalizedEntry, NormalizedEntryType, LogEvent } from "./types";

type LogEventInput = {
  id?: string;
  stream?: string;
  content?: string;
  task_id?: string | null;
  execution_process_id?: string | null;
  created_at?: string | null;
};

function tryParseJSON(line: string): Record<string, unknown> | null {
  if (typeof line !== "string") return null;
  const trimmed = line.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

function stripAnsi(str: string): string {
  return str.replace(/\x1B\[[0-9;]*[mK]/g, "");
}

function extractPreview(val: unknown): string {
  if (typeof val === "string") return val.slice(0, 200);
  if (val == null) return "";
  const s = JSON.stringify(val);
  return s.slice(0, 200);
}

function itemIdToIdx(itemId: string): string {
  const m = String(itemId).match(/item_(\d+)/);
  return m ? m[1] : String(itemId);
}

function itemHasContent(item: Record<string, unknown> | null): boolean {
  if (!item) return false;
  const itemType = normalizeItemType(item.type as string | undefined);
  if (itemType === "agent_message" && item.text) return true;
  if (itemType === "command_execution" && (item.command || item.aggregated_output)) return true;
  return false;
}

function normalizeItemType(type: string | undefined): string {
  if (type === "agentMessage") return "agent_message";
  if (type === "commandExecution") return "command_execution";
  return type || "";
}

function normalizeNotificationEvent(
  event: Record<string, unknown>,
  idx: number,
  keyBase = `norm-${idx}`
): NormalizedEntry | null {
  const method = typeof event.method === "string" ? event.method.replaceAll("/", ".") : "";
  if (!method) return null;

  const params = event.params && typeof event.params === "object" ? (event.params as Record<string, unknown>) : {};
  if (method === "error") {
    const errorPayload = params.error && typeof params.error === "object" ? params.error as Record<string, unknown> : null;
    return {
      id: `${keyBase}-error`,
      timestamp: new Date().toISOString(),
      type: "error",
      label: "Error",
      content: (errorPayload?.message as string) || (params.message as string) || JSON.stringify(params),
    };
  }

  const unwrapped: Record<string, unknown> = {
    ...params,
    type: method,
  };

  if (params.item && typeof params.item === "object") {
    unwrapped.item = params.item;
  }

  if (params.threadId && !unwrapped.thread_id) {
    unwrapped.thread_id = params.threadId;
  }
  if (params.turn && typeof params.turn === "object") {
    (unwrapped as Record<string, unknown>).turn = params.turn;
  }

  if (method === "item.agentMessage.delta") {
    return {
      id: `${keyBase}-${(params.itemId || params.item_id || "agent-delta") as string}`,
      timestamp: new Date().toISOString(),
      type: "assistant" as NormalizedEntryType,
      label: "Assistant",
      content: typeof params.delta === "string" ? params.delta : "",
      itemId: (params.itemId || params.item_id || null) as string | null,
    };
  }

  return normalizeCodexEvent(unwrapped, idx, keyBase);
}

function normalizeClaudeEvent(
  event: Record<string, unknown>,
  idx: number,
  keyBase = `norm-${idx}`
): NormalizedEntry | null {
  const base: { id: string; timestamp: string; type: NormalizedEntryType; label: string; content: string; [key: string]: unknown } = {
    id: (event.uuid as string) || `${keyBase}-claude`,
    timestamp: new Date().toISOString(),
    type: "status",
    label: "",
    content: "",
  };

  switch (event.type) {
    case "help_requested":
      return { ...base, type: "help", label: "Help Requested", content: `Waiting for ${(event.target as string) || "helper"} (${(event.help_request_id as string) || "pending"})`, variant: "requested" };
    case "help_child_started":
      return { ...base, type: "help", label: "Help Child Started", content: `Child task ${(event.child_task_id as string) || ""} is running`, variant: "started" };
    case "help_completed":
      return { ...base, type: "help", label: "Help Completed", content: ((event.result as Record<string, unknown>)?.result as Record<string, unknown>)?.raw_result as string || (event.result as Record<string, unknown>)?.raw_result as string || "Help request completed", variant: "completed" };
    case "help_failed":
      return { ...base, type: "help", label: "Help Failed", content: (event.error as Record<string, unknown>)?.message as string || ((event.result as Record<string, unknown>)?.error as Record<string, unknown>)?.message as string || "Help request failed", variant: "failed" };
    case "task_resumed":
      return { ...base, type: "help", label: "Task Resumed", content: `Resumed after help request ${(event.help_request_id as string) || ""}`, variant: "resumed" };
    case "assistant":
      if (event.message && Array.isArray((event.message as Record<string, unknown>).content)) {
        const content = (event.message as Record<string, unknown>).content as Array<{ type: string; text?: string; thinking?: unknown }>;
        const textParts = content
          .filter((c) => c.type === "text")
          .map((c) => c.text)
          .join("");
        if (textParts) {
          return { ...base, type: "assistant", label: "Assistant", content: textParts };
        }
        const thinking = content.find((c) => c.type === "thinking");
        if (thinking) {
          return { ...base, type: "status", label: "Thinking", content: "Claude is strategizing..." };
        }
      }
      return null;
    case "text_delta":
      return { ...base, type: "assistant", label: "Assistant", content: (event.delta as string) || "" };
    case "tool_use":
      return {
        ...base,
        type: "command",
        label: "bash",
        command: (event.name === "Bash" ? ((event.input as Record<string, unknown>)?.command as string) || "bash" : (event.name as string)) || "bash",
        status: "running" as const,
      };
    case "tool_result":
      return {
        ...base,
        type: "command",
        label: "bash ✓",
        output: extractPreview(event.output),
        status: "success" as const,
        exitCode: 0,
      };
    case "result":
      if (event.subtype === "success") {
        return { ...base, type: "status", label: "Done", content: "Turn completed" };
      }
      return null;
    case "error":
    case "api_error":
      return {
        ...base,
        type: "error",
        label: "Error",
        content: (event.message as string) || (event.error as string) || "Execution error",
      };
    case "system":
      if (["hook_started", "hook_response", "init"].includes(event.subtype as string)) {
        return null;
      }
      if (event.subtype === "api_retry") {
        return {
          ...base,
          type: "status",
          label: "Retrying",
          content: `API Rate Limited. Retry ${event.attempt}/${event.max_retries}...`,
        };
      }
      return null;
    default:
      return null;
  }
}

function normalizeCodexEvent(
  event: Record<string, unknown>,
  idx: number,
  keyBase = `norm-${idx}`
): NormalizedEntry | null {
  const type = (event.type as string) || "";
  const item = (event.item || {}) as Record<string, unknown>;
  const itemId = (item.id as string) || `item-${idx}`;
  const itemType = (item.type as string) || "";

  if (type === "item.completed" && !itemHasContent(item)) {
    return null;
  }

  const base: { id: string; timestamp: string } = {
    id: `${keyBase}-${itemIdToIdx(itemId)}`,
    timestamp: (item.created_at as string) || new Date().toISOString(),
  };
  const normalizedItemType = normalizeItemType(itemType);

  if (type === "item.started") {
    if (normalizedItemType === "command_execution") {
      return {
        ...base,
        type: "command" as NormalizedEntryType,
        label: "bash",
        command: (item.command as string) || "",
        status: "running" as const,
      };
    }
    return null;
  }

  if (type === "item.completed") {
    if (normalizedItemType === "agent_message") {
      return {
        ...base,
        type: "assistant" as NormalizedEntryType,
        label: "Assistant",
        content: (item.text as string) || "",
      };
    }
    if (normalizedItemType === "command_execution") {
      const exitCode = (item.exit_code as number) ?? 0;
      return {
        ...base,
        type: "command" as NormalizedEntryType,
        label: exitCode === 0 ? "bash ✓" : `bash ✗ (${exitCode})`,
        command: (item.command as string) || "",
        output: (item.aggregated_output as string) || "",
        exitCode,
        status: (exitCode === 0 ? "success" : "failed") as "success" | "failed",
      };
    }
  }

  if (type === "thread.started" || type === "turn.started" || type === "turn.completed") {
    const turn = event.turn && typeof event.turn === "object" ? event.turn as Record<string, unknown> : null;
    const failed = type === "turn.completed" && ((turn?.status as string) || "").toLowerCase() === "failed";
    if (failed) {
      const errorPayload = turn?.error && typeof turn.error === "object" ? turn.error as Record<string, unknown> : null;
      return {
        ...base,
        type: "error" as NormalizedEntryType,
        label: "Turn Failed",
        content: (errorPayload?.message as string) || "Codex turn failed",
      };
    }
    return {
      ...base,
      type: "status" as NormalizedEntryType,
      label: type.split(".")[1] || "",
      content: type === "turn.completed" ? "Turn finished" : "",
    };
  }

  return null;
}

function normalizeSingle(log: LogEventInput, idx: number): NormalizedEntry | { id: string; type: "hidden"; hidden: true } {
  const { stream, content } = log;
  const keyBase = log?.id ? `norm-${log.id}` : `norm-${idx}`;
  const safeContent = typeof content === "string"
    ? content
    : content == null
      ? ""
      : JSON.stringify(content);

  if (stream === "stderr") {
    const stripped = stripAnsi(safeContent);
    return {
      id: keyBase,
      type: "raw",
      label: "stderr",
      content: stripped,
      raw: safeContent,
      executionProcessId: log.execution_process_id || null,
    };
  }

  if (stream === "error") {
    const stripped = stripAnsi(safeContent);
    return {
      id: keyBase,
      type: "error",
      label: "Error",
      content: stripped,
      raw: safeContent,
      executionProcessId: log.execution_process_id || null,
      timestamp: log.created_at || undefined,
    };
  }

  if (stream === "runtime") {
    return {
      id: keyBase,
      type: "status",
      label: "Runtime",
      content: safeContent,
      raw: safeContent,
      executionProcessId: log.execution_process_id || null,
      timestamp: log.created_at || undefined,
    };
  }

  const event = tryParseJSON(safeContent);
  if (!event) {
    return {
      id: keyBase,
      type: "raw",
      label: "output",
      content: safeContent,
      raw: safeContent,
      executionProcessId: log.execution_process_id || null,
    };
  }

  if (stream === "notification") {
    const notification = normalizeNotificationEvent(event, idx, keyBase);
    if (notification === null) {
      return { id: `skip-${idx}`, type: "hidden", hidden: true };
    }
    if (notification) {
      return {
        ...notification,
        executionProcessId: log.execution_process_id || notification.executionProcessId || null,
        timestamp: log.created_at || notification.timestamp,
      };
    }
  }

  const normalized = normalizeEvent(event, idx, keyBase);

  if (normalized === null) {
    return { id: `skip-${idx}`, type: "hidden", hidden: true };
  }

  if (normalized) {
    return {
      ...normalized,
      executionProcessId: log.execution_process_id || normalized.executionProcessId || null,
      timestamp: log.created_at || normalized.timestamp,
    };
  }

  const keys = Object.keys(event);
  if (keys.length > 0) {
    const preview = keys
      .slice(0, 3)
      .map((k) => `${k}: ${extractPreview(event[k])}`)
      .join(", ");
    return {
      id: keyBase,
      type: "raw",
      label: "event",
      content: preview,
      raw: safeContent,
      executionProcessId: log.execution_process_id || null,
    };
  }

  return {
    id: keyBase,
    type: "raw",
    label: "output",
    content: safeContent,
    raw: safeContent,
    executionProcessId: log.execution_process_id || null,
  };
}

function normalizeEvent(
  event: Record<string, unknown>,
  idx: number,
  keyBase = `norm-${idx}`
): NormalizedEntry | null {
  if (event.item) {
    return normalizeCodexEvent(event, idx, keyBase);
  } else if (event.method) {
    return normalizeNotificationEvent(event, idx, keyBase);
  } else if (event.type) {
    return normalizeClaudeEvent(event, idx, keyBase);
  }
  return null;
}

function foldEntries(entries: NormalizedEntry[]): NormalizedEntry[] {
  const folded: NormalizedEntry[] = [];
  for (const entry of entries) {
    const last = folded[folded.length - 1];

    if (
      last &&
      last.type === "assistant" &&
      entry.type === "assistant" &&
      last.executionProcessId === entry.executionProcessId
    ) {
      const lastContent = last.content || "";
      const nextContent = entry.content || "";
      if (nextContent && (lastContent.endsWith(nextContent) || nextContent.startsWith(lastContent))) {
        last.content = nextContent.length >= lastContent.length ? nextContent : lastContent;
      } else {
        last.content += nextContent;
      }
      continue;
    }

    if (
      last &&
      last.type === "command" &&
      last.status === "running" &&
      entry.type === "command" &&
      entry.status === "success" &&
      !entry.command
    ) {
      last.output = entry.output;
      last.status = "success";
      last.label = "bash ✓";
      last.exitCode = 0;
      continue;
    }

    folded.push(entry);
  }
  return folded;
}

export function normalizeLogs(logs: LogEventInput[]): NormalizedEntry[] {
  if (!Array.isArray(logs)) return [];
  const entries = logs
    .map((log, idx) => normalizeSingle(log, idx))
    .filter((entry): entry is NormalizedEntry => !entry.hidden);
  return foldEntries(entries);
}
