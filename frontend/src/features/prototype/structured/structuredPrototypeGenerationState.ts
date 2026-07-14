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

const PROJECT_ANALYSIS_DEFAULT_BRIEF =
  "Analyze the registered project source and generate the smallest coherent editable prototype " +
  "from its routes, pages, domain entities, roles, APIs, and observable business flows.";

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

export function structuredPrototypeGenerationBrief(brief: string): string {
  const trimmed = brief.trim();
  return trimmed || PROJECT_ANALYSIS_DEFAULT_BRIEF;
}
