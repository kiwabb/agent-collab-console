import type { StructuredPrototypeCommandApplicationResult } from "./useStructuredPrototypeStudio";

export function resolveStructuredPrototypeCreatedPageId(
  previousPageIds: readonly string[],
  allocationKey: string,
  application: StructuredPrototypeCommandApplicationResult,
): string | null {
  const previousIds = new Set(previousPageIds);
  if (previousIds.size !== previousPageIds.length) return null;
  const pages = application.draft.document.pages;
  if (!previousPageIds.every((pageId) => pages.some((page) => page.id === pageId))) return null;
  const createdPages = pages.filter((page) => !previousIds.has(page.id));
  if (createdPages.length !== 1) return null;

  if (application.allocatedEntityIds !== null) {
    const allocations = application.allocatedEntityIds.filter(
      (allocation) => allocation.newNodeKey === allocationKey,
    );
    if (allocations.length !== 1) return null;
    const pageId = allocations[0]?.entityId;
    return pageId !== undefined && createdPages[0]?.id === pageId ? pageId : null;
  }

  return createdPages[0]?.id ?? null;
}

export function resolveStructuredPrototypeNearestSurvivingPageId(
  pages: readonly { id: string }[],
  deletedPageId: string,
): string | null {
  if (pages.length <= 1) return null;
  const deletedIndex = pages.findIndex((page) => page.id === deletedPageId);
  if (deletedIndex < 0) return null;
  return pages[deletedIndex + 1]?.id ?? pages[deletedIndex - 1]?.id ?? null;
}
