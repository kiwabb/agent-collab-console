export const PROJECT_CONDUCTOR_TEXT_COLLAPSE_AT = 240;
export const PROJECT_CONDUCTOR_MEMORY_PAGE_SIZE = 3;

export function shouldCollapseProjectConductorText(
  text: string,
  threshold = PROJECT_CONDUCTOR_TEXT_COLLAPSE_AT,
): boolean {
  return text.length > threshold;
}

export function nextProjectConductorVisibleCount(
  current: number,
  total: number,
  pageSize = PROJECT_CONDUCTOR_MEMORY_PAGE_SIZE,
): number {
  return Math.min(total, current + pageSize);
}

export function projectConductorHotEventBody(item: Record<string, unknown>): string {
  const role = typeof item["role"] === "string" ? item["role"] : "event";
  const content = typeof item["content"] === "string" ? item["content"] : "";
  return content ? `${role}: ${content}` : role;
}
