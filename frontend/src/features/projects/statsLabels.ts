/**
 * Centralized labels for the project stats strip. The backend field
 * `workspaces` actually counts *issues* (per `ProjectStats` shape in
 * backend/app/domain/models.py), so we deliberately label it "Issues" here
 * rather than mirror the misleading legacy "工作区" copy.
 */
export const STATS_LABELS = {
  total: "Issues",
  open: "Open",
  merged: "Merged",
  abandoned: "Abandoned",
} as const;
