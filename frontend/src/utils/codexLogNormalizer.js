/**
 * Codex JSON Log Normalizer
 *
 * Transforms raw LogEvent[] from `codex exec --json` stdout into
 * NormalizedEntry[] for the execution timeline UI.
 *
 * Real Codex protocol (verified from sqlite3 backend/console.db):
 * - `{"type":"thread.started","thread_id":"..."}`               → status
 * - `{"type":"turn.started"}`                                  → status
 * - `{"type":"turn.completed","usage":{...}}`                  → status (token count)
 * - `{"type":"turn.failed","error":{"message":"..."}}`         → error
 * - `{"type":"error","message":"..."}`                         → error
 * - `{"type":"item.started","item":{"id":"item_0","type":"agent_message"}}`
 * - `{"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"...","status":"in_progress"}}`
 * - `{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"..."}}`
 * - `{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"...","aggregated_output":"...","exit_code":0}}`
 *
 * Item types observed: `agent_message`, `command_execution`
 */

/**
 * @typedef {"status" | "error" | "assistant" | "command" | "help" | "raw"} NormalizedEntryType
 *
 * @typedef {Object} NormalizedEntry
 * @property {string} id
 * @property {NormalizedEntryType} type
 * @property {string} label       - Short label shown in timeline
 * @property {string} content    - Primary text content (markdown for assistant)
 * @property {string} [command]   - Full command (for command type)
 * @property {string} [output]   - Command stdout preview (for command type)
 * @property {string} [exitCode] - Exit code (for command type)
 * @property {string} [status]   - Status: "running" | "success" | "failed"
 */

/**
 * @param {string} line
 * @returns {object|null}
 */
function tryParseJSON(line) {
  if (typeof line !== "string") return null;
  const trimmed = line.trim();
  if (!trimmed.startsWith("{")) return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}

/**
 * Strip ANSI escape codes from a string.
 * @param {string} str
 * @returns {string}
 */
function stripAnsi(str) {
  return str.replace(/\x1B\[[0-9;]*[mK]/g, "");
}

/**
 * Extract a preview string from a value.
 * @param {any} val
 * @returns {string}
 */
function extractPreview(val) {
  if (typeof val === "string") return val.slice(0, 200);
  if (val == null) return "";
  const s = JSON.stringify(val);
  return s.slice(0, 200);
}

/**
 * Convert item id to a short index string for stable id generation.
 * e.g. "item_0" → "0", "item_1" → "1"
 * @param {string} itemId
 * @returns {string}
 */
function itemIdToIdx(itemId) {
  const m = String(itemId).match(/item_(\d+)/);
  return m ? m[1] : String(itemId);
}

/**
 * Determine if an item has meaningful displayable content.
 * @param {object} item
 * @returns {boolean}
 */
function itemHasContent(item) {
  if (!item) return false;
  const itemType = normalizeItemType(item.type);
  if (itemType === "agent_message" && item.text) return true;
  if (itemType === "command_execution" && (item.command || item.aggregated_output)) return true;
  return false;
}

/**
 * Normalize Codex item type variants to snake_case.
 * @param {string} type
 * @returns {string}
 */
function normalizeItemType(type) {
  if (type === "agentMessage") return "agent_message";
  if (type === "commandExecution") return "command_execution";
  return type || "";
}

/**
 * Normalize a single parsed Codex JSON event into a NormalizedEntry.
 * Returns null to skip the event entirely (no noise).
 * @param {object} event  - parsed JSON object from Codex stdout
 * @param {number} idx    - array index used for fallback id
 * @returns {NormalizedEntry|null}
 */
/**
 * Main normalization entry point. Detects protocol and dispatches.
 */
function normalizeEvent(event, idx, keyBase = `norm-${idx}`) {
  // 1. Detect protocol shape: newer Codex JSONL events are item-wrapped, older flat streams are handled separately
  if (event.item) {
    return normalizeCodexEvent(event, idx, keyBase);
  } else if (event.method) {
    return normalizeNotificationEvent(event, idx, keyBase);
  } else if (event.type) {
    return normalizeClaudeEvent(event, idx, keyBase);
  }
  return null;
}

/**
 * Normalizer for JSON-RPC notification logs emitted by the app-server bridge.
 *
 * These arrive as `{method, params}` records in the log table, so we unwrap the
 * payload into the same flat event shape used by the existing Codex renderer.
 */
function normalizeNotificationEvent(event, idx, keyBase = `norm-${idx}`) {
  const method = typeof event.method === "string" ? event.method.replaceAll("/", ".") : "";
  if (!method) {
    return null;
  }

  const params = event.params && typeof event.params === "object" ? event.params : {};
  const unwrapped = {
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
    unwrapped.turn = params.turn;
  }

  if (method === "item.agentMessage.delta") {
    return {
      id: `${keyBase}-${params.itemId || params.item_id || "agent-delta"}`,
      timestamp: new Date().toISOString(),
      type: "assistant",
      label: "Assistant",
      content: typeof params.delta === "string" ? params.delta : "",
      itemId: params.itemId || params.item_id || null,
    };
  }

  return normalizeCodexEvent(unwrapped, idx, keyBase);
}

/**
 * Normalizer for flat stream-json style events.
 */
function normalizeClaudeEvent(event, idx, keyBase = `norm-${idx}`) {
  const base = {
    id: event.uuid || `${keyBase}-claude`,
    timestamp: new Date().toISOString(),
  };

  switch (event.type) {
    case "help_requested":
      return { ...base, type: "help", label: "Help Requested", content: `Waiting for ${event.target || "helper"} (${event.help_request_id || "pending"})`, variant: "requested" };
    case "help_child_started":
      return { ...base, type: "help", label: "Help Child Started", content: `Child task ${event.child_task_id || ""} is running`, variant: "started" };
    case "help_completed":
      return { ...base, type: "help", label: "Help Completed", content: event.result?.result?.raw_result || event.result?.raw_result || "Help request completed", variant: "completed" };
    case "help_failed":
      return { ...base, type: "help", label: "Help Failed", content: event.error?.message || event.result?.error?.message || "Help request failed", variant: "failed" };
    case "task_resumed":
      return { ...base, type: "help", label: "Task Resumed", content: `Resumed after help request ${event.help_request_id || ""}`, variant: "resumed" };
    // Nested assistant message content array
    case "assistant":
      if (event.message && Array.isArray(event.message.content)) {
        const textParts = event.message.content
          .filter((c) => c.type === "text")
          .map((c) => c.text)
          .join("");
        if (textParts) {
          return { ...base, type: "assistant", label: "Assistant", content: textParts };
        }
        const thinking = event.message.content.find((c) => c.type === "thinking");
        if (thinking) {
          return { ...base, type: "status", label: "Thinking", content: "Claude is strategizing..." };
        }
      }
      return null;

    // Streaming text delta (legacy/alternative format)
    case "text_delta":
      return {
        ...base,
        type: "assistant",
        label: "Assistant",
        content: event.delta || "",
      };

    case "tool_use":
      return {
        ...base,
        type: "command",
        label: "bash",
        command: event.name === "Bash" ? (event.input?.command || "bash") : event.name,
        status: "running",
      };

    case "tool_result":
      return {
        ...base,
        type: "command",
        label: "bash ✓",
        output: extractPreview(event.output),
        status: "success",
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
        content: event.message || event.error || "Execution error",
      };

    case "system":
      // Filter lifecycle noise — these have no useful user-facing content
      if (["hook_started", "hook_response", "init"].includes(event.subtype)) {
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

/**
 * Normalizer for Codex protocol (item.started / item.completed).
 */
function normalizeCodexEvent(event, idx, keyBase = `norm-${idx}`) {
  const type = event.type || "";
  const item = event.item || {};
  const itemId = item.id || `item-${idx}`;
  const itemType = item.type || "";

  // Noise filter for empty completions
  if (type === "item.completed" && !itemHasContent(item)) {
    return null;
  }

  const base = {
    id: `${keyBase}-${itemIdToIdx(itemId)}`,
    timestamp: item.created_at || new Date().toISOString(),
  };
  const normalizedItemType = normalizeItemType(itemType);

  if (type === "item.started") {
    if (normalizedItemType === "command_execution") {
      return {
        ...base,
        type: "command",
        label: "bash",
        command: item.command || "",
        status: "running",
      };
    }
    return null; // agent_message started is noise
  }

  if (type === "item.completed") {
    if (normalizedItemType === "agent_message") {
      return {
        ...base,
        type: "assistant",
        label: "Assistant",
        content: item.text || "",
      };
    }
    if (normalizedItemType === "command_execution") {
      const exitCode = item.exit_code ?? 0;
      return {
        ...base,
        type: "command",
        label: exitCode === 0 ? "bash ✓" : `bash ✗ (${exitCode})`,
        command: item.command || "",
        output: item.aggregated_output || "",
        exitCode,
        status: exitCode === 0 ? "success" : "failed",
      };
    }
  }

  // Lifecycle events
  if (type === "thread.started" || type === "turn.started" || type === "turn.completed") {
    return {
      ...base,
      type: "status",
      label: type.split(".")[1],
      content: type === "turn.completed" ? "Turn finished" : "",
    };
  }

  return null;
}

/**
 * @param {object} log   - LogEvent from API
 * @param {number} idx   - Index for fallback id generation
 * @returns {NormalizedEntry}
 */
function normalizeSingle(log, idx) {
  const { stream, content } = log;
  const keyBase = log?.id ? `norm-${log.id}` : `norm-${idx}`;
  const safeContent = typeof content === "string"
    ? content
    : content == null
      ? ""
      : JSON.stringify(content);

  // stderr always raw
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

  // Non-JSON stdout → raw
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

  // Try to normalize via real Codex/Claude protocol
  const normalized = normalizeEvent(event, idx, keyBase);

  // null means the event was intentionally silenced (noise filter) — do not fall through
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

  // Defensive fallback for unknown JSON
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

/**
 * Fold consecutive entries of the same type to avoid UI fragmentation.
 * - Consecutive `assistant` text chunks are merged into one message.
 * - A `command` running entry followed by a `command` success (no command string) gets its output merged.
 * @param {NormalizedEntry[]} entries
 * @returns {NormalizedEntry[]}
 */
function foldEntries(entries) {
  const folded = [];
  for (const entry of entries) {
    const last = folded[folded.length - 1];

    // Merge consecutive assistant text chunks
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

    // Merge command tool result (success, no command string) into running command
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

/**
 * @param {object[]} logs
 * @returns {NormalizedEntry[]}
 */
export function normalizeLogs(logs) {
  if (!Array.isArray(logs)) return [];
  const entries = logs
    .map((log, idx) => normalizeSingle(log, idx))
    .filter((entry) => !entry.hidden);
  return foldEntries(entries);
}
