import type {
  StructuredPrototypeGenerationJob,
  StructuredPrototypeGenerationJobStatus,
} from "./types";

const ACTIVE_GENERATION_STATUSES = new Set<StructuredPrototypeGenerationJobStatus>([
  "queued",
  "planning",
  "generating",
  "assembling",
  "validating",
  "rendering_preview",
]);

export function isStructuredPrototypeGenerationActive(
  status: StructuredPrototypeGenerationJobStatus,
): boolean {
  return ACTIVE_GENERATION_STATUSES.has(status);
}

export function structuredPrototypeGenerationPercent(
  job: StructuredPrototypeGenerationJob,
): number {
  if (job.total === 0) return 0;
  return Math.round((job.processed / job.total) * 100);
}

export function canStartStructuredPrototypeGeneration(
  job: StructuredPrototypeGenerationJob | null,
): boolean {
  return (
    job === null ||
    job.status === "failed" ||
    job.status === "interrupted" ||
    job.status === "cancelled"
  );
}
