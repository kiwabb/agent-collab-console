/**
 * Pure presentation helpers for project remote-update detection.
 *
 * Kept free of React / i18n imports so they can be unit-tested in isolation:
 * callers pass a `translate` function (the i18n `t`, which does NOT interpolate)
 * and these helpers handle the `{n}`/`{branch}` substitution themselves —
 * matching the existing `t("...").replace("{n}", ...)` pattern in ProjectsPage.
 */
import type { ProjectPullResult, ProjectRemoteStatus } from "@/lib/types";

type Translate = (key: string) => string;

/** Visual emphasis for the branch-row badge. The component maps this to classes. */
export type RemoteBadgeTone = "info" | "success" | "action" | "warn" | "muted";

export interface RemoteBadgeDescriptor {
  /** Short badge text, e.g. "落后 2" / "Up to date". */
  label: string;
  /** Tooltip / aria explanation. */
  title: string;
  tone: RemoteBadgeTone;
  /** Whether the Sync button should be enabled (mirrors backend can_fast_forward). */
  canSync: boolean;
}

function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.replace(`{${key}}`, String(value)),
    template,
  );
}

/**
 * Describe a remote status for the badge. Returns null while the status is still
 * loading (caller shows a "checking…" affordance instead).
 */
export function describeRemoteStatus(
  status: ProjectRemoteStatus | null,
  t: Translate,
): RemoteBadgeDescriptor | null {
  if (status === null) return null;

  const branch = status.branch || status.current_branch || "main";

  // Degraded states first — these can't be compared/synced.
  if (status.error === "no_origin" || status.error === "not_a_git_repo") {
    return {
      label: t("projects.updateNoOrigin"),
      title: t("projects.updateNoOriginTitle"),
      tone: "muted",
      canSync: false,
    };
  }
  if (status.error === "fetch_failed") {
    return {
      label: t("projects.updateOffline"),
      title: t("projects.updateOfflineTitle"),
      tone: "warn",
      canSync: false,
    };
  }
  if (status.error === "no_remote_branch") {
    return {
      label: t("projects.updateNoRemoteBranch"),
      title: fill(t("projects.updateNotOnDefaultTitle"), { branch }),
      tone: "muted",
      canSync: false,
    };
  }

  // Clean comparison available.
  if (status.dirty && status.behind > 0) {
    return {
      label: t("projects.updateDirty"),
      title: t("projects.updateDirtyTitle"),
      tone: "warn",
      canSync: false,
    };
  }
  if (status.ahead > 0) {
    return {
      label: t("projects.updateDiverged"),
      title: t("projects.updateDivergedTitle"),
      tone: "warn",
      canSync: false,
    };
  }
  if (status.current_branch !== status.branch) {
    return {
      label:
        status.behind > 0
          ? fill(t("projects.updateBehind"), { n: status.behind })
          : t("projects.updateUpToDate"),
      title: fill(t("projects.updateNotOnDefaultTitle"), { branch }),
      tone: "muted",
      canSync: false,
    };
  }
  if (status.behind > 0) {
    return {
      label: fill(t("projects.updateBehind"), { n: status.behind }),
      title: fill(t("projects.updateBehindTitle"), { n: status.behind }),
      tone: "action",
      canSync: status.can_fast_forward,
    };
  }
  return {
    label: t("projects.updateUpToDate"),
    title: fill(t("projects.updateUpToDateTitle"), { branch }),
    tone: "success",
    canSync: false,
  };
}

export interface PullToast {
  type: "success" | "error" | "warning" | "info";
  title: string;
}

/** Map a pull result (success or structured refusal) to a toast. */
export function describePullResult(result: ProjectPullResult, t: Translate): PullToast {
  if (result.success) {
    return {
      type: "success",
      title: fill(t("projects.syncSuccess"), { n: result.behind_before ?? 0 }),
    };
  }
  switch (result.reason) {
    case "already_up_to_date":
      return { type: "info", title: t("projects.syncNoop") };
    case "dirty":
      return { type: "warning", title: t("projects.syncFailedDirty") };
    case "diverged":
      return { type: "warning", title: t("projects.syncFailedDiverged") };
    case "not_on_default":
      return { type: "warning", title: t("projects.syncFailedNotOnDefault") };
    case "no_origin":
    case "no_remote_branch":
      return { type: "error", title: t("projects.syncFailedNoOrigin") };
    case "fetch_failed":
      return { type: "error", title: t("projects.syncFailedOffline") };
    default:
      return { type: "error", title: t("projects.syncFailed") };
  }
}
