import type { Workspace } from "@/lib/types";

/**
 * Pick a user-facing label for a workspace.
 *
 * Old data sometimes has 1-character titles ("1", "2"); they're meaningless
 * in UI and the ID prefix actually helps distinguish them. We treat any
 * title shorter than 3 chars as "anonymous" and fall back to `Workspace #ab12cd34`.
 */
export function workspaceLabel(ws: Pick<Workspace, "id" | "title">): string {
  const title = (ws.title || "").trim();
  if (title.length >= 3) return title;
  return `Workspace #${ws.id.slice(0, 8)}`;
}
