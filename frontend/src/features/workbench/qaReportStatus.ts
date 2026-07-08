import { safeJsonRecord } from "@/lib/utils";

const QA_REPORT_STATUSES = ["passed", "failed", "blocked", "needs_follow_up"] as const;

export type QaReportStatus = (typeof QA_REPORT_STATUSES)[number];

export function isQaReportStatus(value: unknown): value is QaReportStatus {
  return typeof value === "string" && (QA_REPORT_STATUSES as readonly string[]).includes(value);
}

export function readQaReportStatus(
  artifacts: Array<{ name?: string | undefined; content?: unknown }>,
): QaReportStatus | null {
  const qaPlan = artifacts.find((artifact) => artifact.name === "qa/qa_plan.json");
  if (!qaPlan || typeof qaPlan.content !== "string") return null;
  const parsed = safeJsonRecord(qaPlan.content);
  return isQaReportStatus(parsed?.["status"]) ? parsed["status"] : null;
}
