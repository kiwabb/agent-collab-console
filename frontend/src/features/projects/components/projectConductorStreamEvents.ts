import type { ProjectConductorToolEvent } from "@/lib/types";
import { isRecord, safeJsonRecord } from "@/lib/utils";

function hasEventData(event: Event): event is Event & { data: unknown } {
  return "data" in event;
}

function eventData(event: Event): string | null {
  if (!hasEventData(event)) return null;
  const data = event.data;
  return typeof data === "string" ? data : null;
}

export function parseProjectConductorRecord(event: Event): Record<string, unknown> | null {
  const data = eventData(event);
  return data ? safeJsonRecord(data) : null;
}

export function isProjectConductorToolEvent(value: unknown): value is ProjectConductorToolEvent {
  if (!isRecord(value)) return false;
  return (
    typeof value["id"] === "string" &&
    typeof value["name"] === "string" &&
    isRecord(value["input"]) &&
    typeof value["is_error"] === "boolean" &&
    "result" in value
  );
}

export function readProjectConductorToolEvents(value: unknown): ProjectConductorToolEvent[] {
  return Array.isArray(value) && value.every(isProjectConductorToolEvent) ? value : [];
}

export function parseProjectConductorToolEvent(event: Event): ProjectConductorToolEvent | null {
  const record = parseProjectConductorRecord(event);
  return isProjectConductorToolEvent(record) ? record : null;
}
