import type { PrototypeCodeCandidate, PrototypeCodeCandidateAction } from "@/lib/types/prototypes";
import { isRecord, safeJsonParse } from "@/lib/utils";

export interface FailedPrototypeStreamItem {
  prototype_id: string;
  message: string;
}

export interface CodeGenerationSummary {
  created: number;
  regenerated: number;
  skipped: number;
  failed: number;
  unsupported: number;
}

const CODE_CANDIDATE_ACTIONS = new Set<PrototypeCodeCandidateAction>([
  "create",
  "regenerate",
  "skip",
  "unsupported",
]);

const CODE_CANDIDATE_KINDS = new Set<PrototypeCodeCandidate["kind"]>(["page", "route", "feature"]);

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

export function readSseNullableString(
  record: Record<string, unknown>,
  key: string,
): string | null | undefined {
  const value = record[key];
  if (value === null) return null;
  return typeof value === "string" ? value : undefined;
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

export function readCodeCandidateAction(
  record: Record<string, unknown>,
  key: string,
): PrototypeCodeCandidateAction | null {
  const value = record[key];
  return typeof value === "string" &&
    CODE_CANDIDATE_ACTIONS.has(value as PrototypeCodeCandidateAction)
    ? (value as PrototypeCodeCandidateAction)
    : null;
}

function isCodeCandidateKind(value: unknown): value is PrototypeCodeCandidate["kind"] {
  return (
    typeof value === "string" && CODE_CANDIDATE_KINDS.has(value as PrototypeCodeCandidate["kind"])
  );
}

function isPrototypeCodeCandidate(value: unknown): value is PrototypeCodeCandidate {
  if (!isRecord(value)) return false;
  return (
    typeof value["id"] === "string" &&
    typeof value["title"] === "string" &&
    typeof value["route"] === "string" &&
    isCodeCandidateKind(value["kind"]) &&
    typeof value["framework_hint"] === "string" &&
    readStringArrayValue(value["source_paths"]) !== null &&
    typeof value["primary_source_path"] === "string" &&
    typeof value["source_hash"] === "string" &&
    typeof value["source_excerpt"] === "string" &&
    typeof value["editable_brief"] === "string" &&
    readStringArrayValue(value["signals"]) !== null &&
    readCodeCandidateAction(value, "action") !== null &&
    (typeof value["prototype_id"] === "string" || value["prototype_id"] === null) &&
    (typeof value["unsupported_reason"] === "string" || value["unsupported_reason"] === null)
  );
}

function readStringArrayValue(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : null;
}

export function readPrototypeCodeCandidates(
  record: Record<string, unknown>,
  key: string,
): PrototypeCodeCandidate[] | null {
  const value = record[key];
  return Array.isArray(value) && value.every(isPrototypeCodeCandidate) ? value : null;
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

export function readCodeGenerationSummary(
  record: Record<string, unknown>,
): CodeGenerationSummary | null {
  const created = readSseNumber(record, "created");
  const regenerated = readSseNumber(record, "regenerated");
  const skipped = readSseNumber(record, "skipped");
  const failed = readSseNumber(record, "failed");
  const unsupported = readSseNumber(record, "unsupported");
  if (
    created === null ||
    regenerated === null ||
    skipped === null ||
    failed === null ||
    unsupported === null
  ) {
    return null;
  }
  return { created, regenerated, skipped, failed, unsupported };
}
