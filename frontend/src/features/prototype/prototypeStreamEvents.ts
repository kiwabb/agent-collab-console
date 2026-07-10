import { isRecord, safeJsonParse } from "@/lib/utils";

export interface FailedPrototypeStreamItem {
  prototype_id: string;
  message: string;
}

function hasEventData(event: Event): event is Event & { data: unknown } {
  return "data" in event;
}

function eventData(event: Event): unknown {
  return hasEventData(event) ? event.data : null;
}

export function parseSseRecord(event: Event): Record<string, unknown> | null {
  const data = eventData(event);
  if (typeof data !== "string" || data.length === 0) return null;
  const parsed = safeJsonParse(data);
  return isRecord(parsed) ? parsed : null;
}

export function readSseString(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

export function readSseNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function readSseStringArray(record: Record<string, unknown>, key: string): string[] | null {
  const value = record[key];
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
}

export function readSseErrorMessage(event: Event): string | null {
  const record = parseSseRecord(event);
  return record ? readSseString(record, "message") : null;
}

export function readFailedPrototypeItems(
  record: Record<string, unknown>,
  key: string,
): FailedPrototypeStreamItem[] | null {
  const value = record[key];
  if (!Array.isArray(value)) return null;
  const items: FailedPrototypeStreamItem[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    const prototypeId = readSseString(item, "prototype_id");
    const message = readSseString(item, "message");
    if (!prototypeId || !message) return null;
    items.push({ prototype_id: prototypeId, message });
  }
  return items;
}
