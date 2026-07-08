import type { NormalizedEntry } from "./types";
import { classifyTool, extractCommand, pickString, PATH_KEYS, asRecord } from "./toolConstants";
import { safeJsonRecord } from "./utils";

type LogEventInput = {
  id?: string | undefined;
  stream?: string | undefined;
  content?: string | undefined;
  task_id?: string | null | undefined;
  execution_process_id?: string | null | undefined;
  created_at?: string | null | undefined;
};

type HiddenNormalizedEntry = { id: string; type: "hidden"; hidden: true };

function tryParseJSON(line: string): Record<string, unknown> | null {
  if (typeof line !== "string") return null;
  const trimmed = line.trim();
  if (!trimmed.startsWith("{")) return null;
  return safeJsonRecord(trimmed);
}

function stripAnsi(str: string): string {
  return str.replace(/\x1B\[[0-9;]*[mK]/g, "");
}

function extractPreview(val: unknown, max = 200): string {
  if (typeof val === "string") return val.slice(0, max);
  if (val == null) return "";
  try {
    return JSON.stringify(val).slice(0, max);
  } catch {
    return String(val).slice(0, max);
  }
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function optionalString(value: unknown): string | undefined {
  const text = stringValue(value);
  return text || undefined;
}

function nullableString(value: unknown): string | null {
  const text = stringValue(value);
  return text || null;
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    const text = stringValue(value);
    if (text) return text;
  }
  return "";
}

function itemIdToIdx(itemId: string): string {
  const m = String(itemId).match(/item_(\d+)/);
  return m?.[1] ?? String(itemId);
}

function buildToolEntry(
  base: {
    id: string;
    timestamp?: string | undefined;
    executionProcessId?: string | null | undefined;
  },
  opts: {
    toolUseId?: string | undefined;
    toolName?: string | undefined;
    itemType?: string | null | undefined;
    args?: Record<string, unknown> | undefined;
    command?: string | undefined;
    filePath?: string | undefined;
    output?: string | undefined;
    isError?: boolean | undefined;
    status?: string | null | undefined;
    durationMs?: number | null | undefined;
  },
): NormalizedEntry {
  const toolName = opts.toolName || "";
  const category = classifyTool(toolName, opts.itemType);
  const args = opts.args ?? {};
  const filePath =
    opts.filePath || pickString(args, PATH_KEYS) || pickString(asRecord(args["input"]), PATH_KEYS);
  const command = opts.command || extractCommand(args);
  const hasOutput = Boolean(opts.output);
  const status: "running" | "success" | "failed" = opts.isError
    ? "failed"
    : hasOutput || opts.durationMs != null
      ? "success"
      : "running";
  return {
    ...base,
    type: "tool",
    label: toolName || category,
    toolName,
    toolUseId: opts.toolUseId || undefined,
    category,
    args,
    command: command || undefined,
    filePath: filePath || undefined,
    output: opts.output || undefined,
    status,
    isError: opts.isError ?? false,
    durationMs: opts.durationMs ?? undefined,
  };
}

function normalizeNotificationEvent(
  event: Record<string, unknown>,
  _idx: number,
  keyBase: string,
): NormalizedEntry | null {
  const method = typeof event["method"] === "string" ? event["method"].replaceAll("/", ".") : "";
  if (!method) return null;
  const params = asRecord(event["params"]) ?? {};

  if (method === "error") {
    const errorPayload = asRecord(params["error"]);
    return {
      id: `${keyBase}-error`,
      timestamp: new Date().toISOString(),
      type: "error",
      label: "Error",
      content: firstString(errorPayload?.["message"], params["message"]) || JSON.stringify(params),
    };
  }

  if (method === "item.agentMessage.delta" || method === "item.agent_message.delta") {
    const itemId = firstString(params["itemId"], params["item_id"]);
    return {
      id: `${keyBase}-${itemId || "agent-delta"}`,
      timestamp: new Date().toISOString(),
      type: "assistant",
      label: "Assistant",
      content: typeof params["delta"] === "string" ? params["delta"] : "",
      itemId: itemId || null,
    };
  }

  if (method.startsWith("turn.")) {
    const turn = asRecord(event["turn"]) ?? asRecord(params["turn"]);
    const turnStatus = String(turn?.["status"] || params["status"] || "").toLowerCase();
    if (turnStatus === "failed") {
      const err = asRecord(turn?.["error"]) ?? asRecord(params["error"]);
      return {
        id: `${keyBase}-turn`,
        type: "error",
        label: "Turn Failed",
        content: stringValue(err?.["message"]) || "Turn failed",
        timestamp: new Date().toISOString(),
      };
    }
    const eventKind = method.replace("turn.", "");
    return {
      id: `${keyBase}-turn-${eventKind}`,
      type: "status",
      label: eventKind,
      content: eventKind,
      timestamp: new Date().toISOString(),
    };
  }

  if (method === "item.completed") {
    const item = asRecord(params["item"]);
    if (!item) return null;
    const itemType = String(item["type"] || "")
      .replace(/_/g, "")
      .toLowerCase();
    if (itemType === "agentmessage") {
      const text = String(item["text"] || "");
      if (!text) return null;
      return {
        id: `${keyBase}-${String(item["id"] || "item")}`,
        timestamp: stringValue(item["created_at"]) || new Date().toISOString(),
        type: "assistant",
        label: "Assistant",
        content: text,
      };
    }
    if (itemType === "commandexecution") {
      const output = String(item["aggregated_output"] ?? item["output"] ?? "");
      const exitCode = item["exit_code"] != null ? Number(item["exit_code"]) : 0;
      return {
        id: `${keyBase}-${String(item["id"] || "cmd")}`,
        timestamp: new Date().toISOString(),
        type: "command",
        label: "Command",
        command: optionalString(item["command"]),
        output: output || undefined,
        exitCode,
        status: exitCode === 0 ? "success" : "failed",
      };
    }
    return null;
  }

  return null;
}

function normalizeCodexStdoutEvent(
  event: Record<string, unknown>,
  idx: number,
  keyBase: string,
): NormalizedEntry | null {
  const method = typeof event["method"] === "string" ? event["method"] : "";
  if (method.startsWith("item/") || method.startsWith("item.")) return null;
  if (method.startsWith("turn/") || method.startsWith("turn.")) return null;
  if (method === "initialize" || method === "initialized") return null;

  const type = stringValue(event["type"]);
  const item = asRecord(event["item"]) ?? {};
  const itemId = stringValue(item["id"]) || `item-${idx}`;
  const itemType = stringValue(item["type"]);

  if (type === "thread.started" || type === "turn.started" || type === "turn.completed") {
    const turn = asRecord(event["turn"]);
    const failed =
      type === "turn.completed" && String(turn?.["status"] || "").toLowerCase() === "failed";
    if (failed) {
      const err = asRecord(turn?.["error"]);
      return {
        id: `${keyBase}-turn`,
        type: "error",
        label: "Turn Failed",
        content: stringValue(err?.["message"]) || "Codex turn failed",
        timestamp: new Date().toISOString(),
      };
    }
    return null;
  }

  if (type === "item.completed") {
    if (itemType === "agent_message" || itemType === "agentMessage") {
      const text = stringValue(item["text"]);
      if (!text) return null;
      return {
        id: `${keyBase}-${itemIdToIdx(itemId)}`,
        timestamp: stringValue(item["created_at"]) || new Date().toISOString(),
        type: "assistant",
        label: "Assistant",
        content: text,
      };
    }
    return null;
  }

  return null;
}

function normalizeClaudeEvent(
  event: Record<string, unknown>,
  _idx: number,
  keyBase: string,
): NormalizedEntry | null {
  const base: { id: string; timestamp: string } = {
    id: stringValue(event["uuid"]) || `${keyBase}-claude`,
    timestamp: new Date().toISOString(),
  };
  switch (event["type"]) {
    case "help_requested":
      return {
        ...base,
        type: "help",
        label: "Help Requested",
        content: `Waiting for ${stringValue(event["target"]) || "helper"} (${stringValue(event["help_request_id"]) || "pending"})`,
        variant: "requested",
      };
    case "help_child_started":
      return {
        ...base,
        type: "help",
        label: "Help Child Started",
        content: `Child task ${stringValue(event["child_task_id"])} is running`,
        variant: "started",
      };
    case "help_completed": {
      const result = asRecord(event["result"]);
      return {
        ...base,
        type: "help",
        label: "Help Completed",
        content:
          firstString(asRecord(result?.["result"])?.["raw_result"], result?.["raw_result"]) ||
          "Help request completed",
        variant: "completed",
      };
    }
    case "help_failed": {
      const error = asRecord(event["error"]);
      const failedResult = asRecord(event["result"]);
      return {
        ...base,
        type: "help",
        label: "Help Failed",
        content:
          firstString(error?.["message"], asRecord(failedResult?.["error"])?.["message"]) ||
          "Help request failed",
        variant: "failed",
      };
    }
    case "task_resumed":
      return {
        ...base,
        type: "help",
        label: "Task Resumed",
        content: `Resumed after help request ${stringValue(event["help_request_id"])}`,
        variant: "resumed",
      };
    case "assistant": {
      const msg = asRecord(event["message"]);
      const rawContent = msg?.["content"];
      const content = Array.isArray(rawContent) ? rawContent : null;
      if (!content) return null;
      const textParts = content
        .map((c) => {
          const block = asRecord(c);
          if (block?.["type"] === "text") {
            return typeof block["text"] === "string" ? block["text"] : "";
          }
          return "";
        })
        .join("");
      if (textParts) {
        return { ...base, type: "assistant", label: "Assistant", content: textParts };
      }
      return null;
    }
    case "user":
      return null;
    case "text_delta":
      return {
        ...base,
        type: "assistant",
        label: "Assistant",
        content: stringValue(event["delta"]),
      };
    case "result":
      if (event["subtype"] === "success") {
        return { ...base, type: "status", label: "Done", content: "Turn completed" };
      }
      return null;
    case "error":
    case "api_error":
      return {
        ...base,
        type: "error",
        label: "Error",
        content: firstString(event["message"], event["error"]) || "Execution error",
      };
    case "system":
      if (event["subtype"] === "api_retry") {
        return {
          ...base,
          type: "status",
          label: "Retrying",
          content: `Rate limited. Retry ${event["attempt"]}/${event["max_retries"]}…`,
        };
      }
      return null;
    default:
      return null;
  }
}

function normalizeSingle(log: LogEventInput, idx: number): NormalizedEntry | HiddenNormalizedEntry {
  const { stream, content } = log;
  const keyBase = log?.id ? `norm-${log.id}` : `norm-${idx}`;
  const safeContent =
    typeof content === "string" ? content : content == null ? "" : JSON.stringify(content);
  const exec = log.execution_process_id || null;
  const ts = log.created_at || undefined;

  if (stream === "tool_use" || stream === "tool_result" || stream === "tool_event") {
    const payload = tryParseJSON(safeContent);
    if (!payload) return { id: `skip-${idx}`, type: "hidden", hidden: true };
    const kind = optionalString(payload["kind"]);
    const toolUseId = stringValue(payload["tool_use_id"]);
    const id = `tool-${exec || "x"}-${toolUseId || keyBase}`;
    if (kind === "tool_use" || kind === "tool_started") {
      return buildToolEntry(
        { id, timestamp: ts, executionProcessId: exec },
        {
          toolUseId,
          toolName: stringValue(payload["tool_name"]),
          itemType: nullableString(payload["item_type"]),
          args: asRecord(payload["input"]) ?? {},
          command: optionalString(payload["command"]),
          filePath: optionalString(payload["file_path"]),
        },
      );
    }
    if (kind === "tool_result" || kind === "tool_completed") {
      const output =
        typeof payload["output"] === "string"
          ? payload["output"]
          : extractPreview(payload["output"], 4000);
      return buildToolEntry(
        { id, timestamp: ts, executionProcessId: exec },
        {
          toolUseId,
          toolName: stringValue(payload["tool_name"]),
          itemType: nullableString(payload["item_type"]),
          args: asRecord(payload["input"]) ?? {},
          command: optionalString(payload["command"]),
          filePath: optionalString(payload["file_path"]),
          output,
          isError: Boolean(payload["is_error"]),
          status: stringValue(payload["status"]) || "completed",
          durationMs: typeof payload["duration_ms"] === "number" ? payload["duration_ms"] : null,
        },
      );
    }
    return { id: `skip-${idx}`, type: "hidden", hidden: true };
  }

  if (stream === "thinking") {
    const payload = tryParseJSON(safeContent);
    const text = stringValue(payload?.["text"]) || safeContent;
    return {
      id: keyBase,
      type: "thinking",
      label: "Thinking",
      content: text,
      executionProcessId: exec,
      timestamp: ts,
    };
  }

  if (stream === "stderr") {
    const stripped = stripAnsi(safeContent);
    return {
      id: keyBase,
      type: "raw",
      label: "stderr",
      content: stripped,
      raw: safeContent,
      executionProcessId: exec,
      timestamp: ts,
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
      executionProcessId: exec,
      timestamp: ts,
    };
  }

  if (stream === "runtime") {
    return {
      id: keyBase,
      type: "status",
      label: "Runtime",
      content: safeContent,
      raw: safeContent,
      executionProcessId: exec,
      timestamp: ts,
    };
  }

  if (stream === "help_request") {
    return {
      id: keyBase,
      type: "help",
      label: "Help",
      content: safeContent,
      executionProcessId: exec,
      timestamp: ts,
    };
  }

  if (stream === "stdin") {
    return { id: `skip-${idx}`, type: "hidden", hidden: true };
  }

  const event = tryParseJSON(safeContent);
  if (!event) {
    return {
      id: keyBase,
      type: "raw",
      label: "output",
      content: safeContent,
      raw: safeContent,
      executionProcessId: exec,
      timestamp: ts,
    };
  }

  if (stream === "notification") {
    const notification = normalizeNotificationEvent(event, idx, keyBase);
    if (!notification) return { id: `skip-${idx}`, type: "hidden", hidden: true };
    return { ...notification, executionProcessId: exec, timestamp: ts };
  }

  // stream === "stdout" or default
  if (event["method"]) {
    const notification = normalizeNotificationEvent(event, idx, keyBase);
    if (!notification) return { id: `skip-${idx}`, type: "hidden", hidden: true };
    return { ...notification, executionProcessId: exec, timestamp: ts };
  }
  if (event["item"]) {
    const codex = normalizeCodexStdoutEvent(event, idx, keyBase);
    if (!codex) return { id: `skip-${idx}`, type: "hidden", hidden: true };
    return { ...codex, executionProcessId: exec, timestamp: ts };
  }
  if (event["type"]) {
    const claude = normalizeClaudeEvent(event, idx, keyBase);
    if (!claude) return { id: `skip-${idx}`, type: "hidden", hidden: true };
    return { ...claude, executionProcessId: exec, timestamp: ts };
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
      executionProcessId: exec,
      timestamp: ts,
    };
  }

  return {
    id: keyBase,
    type: "raw",
    label: "output",
    content: safeContent,
    raw: safeContent,
    executionProcessId: exec,
    timestamp: ts,
  };
}

function foldEntries(entries: NormalizedEntry[]): NormalizedEntry[] {
  const byUseId = new Map<string, NormalizedEntry>();
  const out: NormalizedEntry[] = [];
  for (const entry of entries) {
    if (entry.type === "tool" && entry.toolUseId) {
      const existing = byUseId.get(entry.toolUseId);
      if (existing) {
        existing.output = entry.output ?? existing.output;
        existing.status = entry.status ?? existing.status;
        existing.isError = entry.isError ?? existing.isError;
        existing.durationMs = entry.durationMs ?? existing.durationMs;
        existing.exitCode = entry.exitCode ?? existing.exitCode;
        existing.toolName = entry.toolName || existing.toolName;
        existing.command = entry.command ?? existing.command;
        existing.filePath = entry.filePath ?? existing.filePath;
        existing.args = entry.args && Object.keys(entry.args).length ? entry.args : existing.args;
        continue;
      }
      byUseId.set(entry.toolUseId, entry);
      out.push(entry);
      continue;
    }
    out.push(entry);
  }

  const folded: NormalizedEntry[] = [];
  for (const entry of out) {
    const last = folded[folded.length - 1];
    if (
      last &&
      last.type === "assistant" &&
      entry.type === "assistant" &&
      last.executionProcessId === entry.executionProcessId
    ) {
      const lastContent = last.content || "";
      const nextContent = entry.content || "";
      if (
        nextContent &&
        (lastContent.endsWith(nextContent) || nextContent.startsWith(lastContent))
      ) {
        last.content = nextContent.length >= lastContent.length ? nextContent : lastContent;
      } else {
        last.content = lastContent + nextContent;
      }
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
    .filter((entry): entry is NormalizedEntry => entry.type !== "hidden");
  return foldEntries(entries);
}
