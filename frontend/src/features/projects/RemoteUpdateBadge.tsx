"use client";

import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";
import type { ProjectRemoteStatus } from "@/lib/types";

import { describeRemoteStatus, type RemoteBadgeTone } from "./projectRemoteStatus";

const TONE_CLASS: Record<RemoteBadgeTone, string> = {
  info: "bg-foreground/10 text-muted-foreground",
  success: "bg-success/10 text-success",
  action: "bg-brand/10 text-brand",
  warn: "bg-warning/10 text-warning",
  muted: "bg-muted text-muted-foreground",
};

/**
 * Small pill rendered beside the project's default branch showing how it
 * relates to its remote: "checking…", "N behind", "up to date", or a degraded
 * reason (local changes / diverged / no remote). Returns the checking state
 * while `status` is still null.
 */
export function RemoteUpdateBadge({
  status,
  checking,
}: {
  status: ProjectRemoteStatus | null;
  checking: boolean;
}) {
  const { t } = useI18n();
  const descriptor = describeRemoteStatus(status, t);

  if (descriptor === null || checking) {
    return (
      <span
        data-density="project-remote-checking"
        className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider bg-foreground/10 text-muted-foreground"
      >
        {t("projects.updateChecking")}
      </span>
    );
  }

  return (
    <span
      data-density="project-remote-status"
      title={descriptor.title}
      aria-label={descriptor.title}
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        TONE_CLASS[descriptor.tone],
      )}
    >
      {descriptor.label}
    </span>
  );
}
