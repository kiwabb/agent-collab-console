import type { NormalizedEntry } from "./types";

function normalizeText(text: string | null | undefined): string {
  return String(text || "").trim();
}

export function shouldShowTopErrorCard(
  errorEntry: Pick<NormalizedEntry, "content"> | null | undefined,
  taskStatus: string | null | undefined,
  taskResult: string | null | undefined,
): boolean {
  if (!errorEntry) return false;

  const errorContent = normalizeText(errorEntry.content);
  if (!errorContent) return false;

  const normalizedStatus = normalizeText(taskStatus).toLowerCase();
  const resultContent = normalizeText(taskResult);

  if (normalizedStatus !== "failed" || !resultContent) {
    return true;
  }

  return !(
    errorContent === resultContent ||
    errorContent.includes(resultContent) ||
    resultContent.includes(errorContent)
  );
}
