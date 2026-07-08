import type { Operation } from "fast-json-patch";

import type { BusEvent } from "@/contexts/ExecutionProcessesContext";
import type { LogEvent } from "@/lib/types";
import { isRecord, safeJsonParse } from "@/lib/utils";

import { isLogEvent } from "./executionProcessStreamFrames";

export type GlobalEventsFrame =
  | { kind: "ping" }
  | { kind: "event"; eventId: string | null; event: BusEvent }
  | { kind: "malformed" };

export type WorkspaceEventsFrame =
  | { kind: "control" }
  | {
      kind: "message";
      patches: Operation[] | null;
      events: LogEvent[] | null;
      ready: boolean;
      finished: boolean;
    }
  | { kind: "malformed" };

function isPatchOperation(value: unknown): value is Operation {
  if (!isRecord(value)) return false;
  return typeof value["op"] === "string" && typeof value["path"] === "string";
}

export function parseGlobalEventsFrame(raw: unknown): GlobalEventsFrame {
  if (typeof raw !== "string") return { kind: "malformed" };
  const parsed = safeJsonParse(raw);
  if (!isRecord(parsed)) return { kind: "malformed" };

  const type = parsed["type"];
  if (type === "ping") return { kind: "ping" };
  if (typeof type !== "string") return { kind: "malformed" };

  const payload = parsed["payload"];
  const eventId = parsed["event_id"];
  return {
    kind: "event",
    eventId: typeof eventId === "string" && eventId.length > 0 ? eventId : null,
    event: {
      ...(isRecord(payload) ? payload : {}),
      type,
    } as BusEvent,
  };
}

export function parseWorkspaceEventsFrame(raw: unknown): WorkspaceEventsFrame {
  if (typeof raw !== "string") return { kind: "malformed" };
  if (raw === "pong" || raw === "ping") return { kind: "control" };

  const parsed = safeJsonParse(raw);
  if (!isRecord(parsed)) return { kind: "malformed" };

  const jsonPatch = parsed["JsonPatch"];
  const events = parsed["Events"];
  const patches =
    jsonPatch === undefined
      ? null
      : Array.isArray(jsonPatch) && jsonPatch.every(isPatchOperation)
        ? jsonPatch
        : undefined;
  const logEvents =
    events === undefined
      ? null
      : Array.isArray(events) && events.every(isLogEvent)
        ? events
        : undefined;

  if (patches === undefined || logEvents === undefined) return { kind: "malformed" };

  return {
    kind: "message",
    patches,
    events: logEvents,
    ready: parsed["Ready"] === true,
    finished: parsed["finished"] === true,
  };
}
