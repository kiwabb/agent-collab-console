import type { CodexTaskMessage, LogEvent } from "@/lib/types";
import { isRecord, safeJsonParse } from "@/lib/utils";

export type MessageStreamFrame =
  | { kind: "finished" }
  | { kind: "message_delta"; seq: number; deltaText: string }
  | { kind: "message"; message: CodexTaskMessage }
  | { kind: "unknown" }
  | { kind: "malformed" };

export type LogStreamFrame =
  | { kind: "control" }
  | { kind: "finished" }
  | { kind: "assistant_delta"; seq: number | null; deltaText: string }
  | {
      kind: "heartbeat";
      phase: string;
      elapsedSinceLastMs: number;
      lastEventAt: number | null;
    }
  | { kind: "log"; log: LogEvent }
  | { kind: "unknown" };

function nullableString(value: unknown): string | null | undefined {
  if (value === null) return null;
  return typeof value === "string" ? value : undefined;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isCodexTaskMessage(value: unknown): value is CodexTaskMessage {
  if (!isRecord(value)) return false;
  return (
    typeof value["id"] === "string" &&
    typeof value["task_id"] === "string" &&
    nullableString(value["execution_process_id"]) !== undefined &&
    typeof value["role"] === "string" &&
    typeof value["content"] === "string" &&
    (value["mentions"] === undefined || isStringArray(value["mentions"])) &&
    (value["issue_refs"] === undefined || isStringArray(value["issue_refs"])) &&
    nullableString(value["created_at"]) !== undefined
  );
}

export function isLogEvent(value: unknown): value is LogEvent {
  if (!isRecord(value)) return false;
  return (
    typeof value["id"] === "string" &&
    typeof value["session_id"] === "string" &&
    typeof value["stream"] === "string" &&
    typeof value["content"] === "string" &&
    nullableString(value["task_id"]) !== undefined &&
    nullableString(value["execution_process_id"]) !== undefined &&
    nullableString(value["created_at"]) !== undefined
  );
}

export function parseMessageStreamFrame(raw: unknown): MessageStreamFrame {
  if (typeof raw !== "string") return { kind: "malformed" };
  const parsed = safeJsonParse(raw);
  if (!isRecord(parsed)) return { kind: "malformed" };

  if (parsed["finished"] === true) return { kind: "finished" };

  if (parsed["type"] === "message_delta") {
    const seq = parsed["seq"];
    const deltaText = parsed["delta_text"];
    if (typeof seq === "number" && Number.isFinite(seq) && typeof deltaText === "string") {
      return { kind: "message_delta", seq, deltaText };
    }
    return { kind: "unknown" };
  }

  if (isCodexTaskMessage(parsed)) {
    return { kind: "message", message: parsed };
  }

  return { kind: "unknown" };
}

export function parseLogStreamFrame(raw: unknown): LogStreamFrame {
  if (typeof raw !== "string" || raw === "pong" || raw.length === 0 || raw[0] !== "{") {
    return { kind: "control" };
  }
  const parsed = safeJsonParse(raw);
  if (!isRecord(parsed)) return { kind: "control" };

  if (parsed["finished"] === true) return { kind: "finished" };

  if (parsed["kind"] === "assistant_delta") {
    const seq = parsed["seq"];
    const deltaText = parsed["delta_text"];
    return {
      kind: "assistant_delta",
      seq: typeof seq === "number" && Number.isFinite(seq) ? seq : null,
      deltaText: typeof deltaText === "string" ? deltaText : "",
    };
  }

  if (parsed["kind"] === "heartbeat") {
    const phase = parsed["phase"];
    const elapsed = parsed["elapsed_since_last_ms"];
    const lastEventAt = parsed["last_event_at"];
    return {
      kind: "heartbeat",
      phase: typeof phase === "string" ? phase : "idle",
      elapsedSinceLastMs: typeof elapsed === "number" && Number.isFinite(elapsed) ? elapsed : 0,
      lastEventAt:
        typeof lastEventAt === "number" && Number.isFinite(lastEventAt) ? lastEventAt : null,
    };
  }

  if (isLogEvent(parsed)) {
    return { kind: "log", log: parsed };
  }

  return { kind: "unknown" };
}
