"use client";

import { useEffect, useRef } from "react";
import { ExternalLink, Play, Square } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import type { ProjectRunLogLine, ProjectRunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

import { deriveProjectRunPresentation, selectProjectRunFailureLine } from "./projectStartupConfig";
import type { ProjectStartupState } from "./projectStartupConfig";

interface Props {
  runStatus: ProjectRunStatus | null;
  runLogs: ProjectRunLogLine[];
  startupState: ProjectStartupState;
  runBusy: boolean;
  isAnalyzing: boolean;
  onStart: () => Promise<void>;
  onStop: () => Promise<void>;
}

export function ProjectRunStatusPanel({
  runStatus,
  runLogs,
  startupState,
  runBusy,
  isAnalyzing,
  onStart,
  onStop,
}: Props) {
  const { t } = useI18n();
  const logEndRef = useRef<HTMLDivElement>(null);
  const managedRunning = runStatus?.running === true;
  const presentation = deriveProjectRunPresentation(runStatus, startupState);
  const externalReachable = presentation === "external_reachable";
  const runFailed = startupState.runOutcome === "failed";
  const runCompleted = startupState.runOutcome === "completed";
  const runStopped = startupState.runOutcome === "stopped";
  const failureLine = selectProjectRunFailureLine(runLogs);
  let title = t("startupConfig.readyTitle");
  let detail = t("startupConfig.notReadyDetail");
  if (startupState.unsavedCount > 0) {
    detail = t("startupConfig.unsavedDetail", { count: startupState.unsavedCount });
  } else if (startupState.missingCount > 0) {
    detail = t("startupConfig.missingDetail", { count: startupState.missingCount });
  } else if (startupState.canStart) {
    detail = t("startupConfig.readyDetail");
  }

  switch (presentation) {
    case "external_reachable":
      title = t("startupConfig.externalServiceTitle");
      detail = t("startupConfig.externalServiceDetail", {
        url: runStatus?.service.url ?? "",
      });
      break;
    case "managed_starting":
      title = t("startupConfig.serviceStartingTitle");
      detail = t("startupConfig.serviceStartingDetail", {
        url: runStatus?.service.url ?? "",
      });
      break;
    case "managed_running":
      title = t("startupConfig.runningTitle");
      detail = t("startupConfig.runningDetail", { command: runStatus?.command ?? "" });
      break;
    case "failed":
      title = t("startupConfig.failedTitle");
      detail = t("startupConfig.failedDetail", {
        code: runStatus?.exit_code ?? "",
        error: failureLine ?? t("startupConfig.failedUnknown"),
      });
      break;
    case "completed":
      title = t("startupConfig.completedTitle");
      detail = t("startupConfig.completedDetail");
      break;
    case "stopped":
      title = t("startupConfig.stoppedTitle");
      detail = t("startupConfig.stoppedDetail");
      break;
    case "offline":
      title = t("startupConfig.serviceOfflineTitle");
      detail = t("startupConfig.serviceOfflineDetail", {
        url: runStatus?.service.url ?? "",
      });
      break;
    case "unknown":
      title = t("startupConfig.serviceUnknownTitle");
      detail = t("startupConfig.serviceUnknownDetail");
      break;
    case "ready":
      break;
  }

  useEffect(() => {
    if (runLogs.length > 0) {
      logEndRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [runLogs]);

  return (
    <>
      <section
        aria-live="polite"
        className={cn(
          "flex flex-col gap-4 rounded-2xl border bg-surface-raised p-5 md:flex-row md:items-center md:justify-between",
          runFailed ? "border-status-failed/50" : "border-border-subtle",
        )}
      >
        <div className="min-w-0">
          <h3 className="text-base font-semibold">{title}</h3>
          <p className="mt-1 break-words text-sm leading-6 text-text-muted">{detail}</p>
        </div>
        {managedRunning ? (
          <Button
            variant="outline"
            onClick={() => void onStop()}
            disabled={runBusy}
            className="min-h-11 shrink-0 gap-2"
          >
            <Square size={15} />
            {runBusy ? t("projects.runStopping") : t("projects.runStop")}
          </Button>
        ) : externalReachable && runStatus?.service.url ? (
          <a
            href={runStatus.service.url}
            target="_blank"
            rel="noreferrer"
            className={cn(buttonVariants({ variant: "outline" }), "min-h-11 shrink-0 gap-2")}
          >
            <ExternalLink size={16} />
            {t("startupConfig.openService")}
          </a>
        ) : (
          <Button
            onClick={() => void onStart()}
            disabled={!startupState.canStart || runBusy || isAnalyzing}
            className="min-h-11 shrink-0 gap-2"
          >
            <Play size={16} />
            {runBusy
              ? t("projects.runStarting")
              : runFailed || runCompleted || runStopped
                ? t("startupConfig.retryRun")
                : t("projects.runStart")}
          </Button>
        )}
      </section>

      {(managedRunning || runLogs.length > 0 || runFailed) && (
        <section
          aria-labelledby="startup-run-logs-heading"
          className="overflow-hidden rounded-2xl border border-border-subtle bg-black/90"
        >
          <div className="flex flex-wrap items-center gap-2 border-b border-border-subtle bg-surface px-4 py-3 text-xs">
            <span
              aria-hidden
              className={cn(
                "inline-block size-2 rounded-full",
                managedRunning
                  ? "animate-pulse bg-status-running"
                  : runFailed
                    ? "bg-status-failed"
                    : "bg-text-muted",
              )}
            />
            <h3 id="startup-run-logs-heading" className="font-semibold">
              {t("startupConfig.runLogsTitle")}
            </h3>
            <span className={cn("text-text-muted", runFailed && "text-status-failed")}>
              {managedRunning
                ? t("startupConfig.runLogsRunning")
                : runStatus?.exit_code !== null
                  ? t("startupConfig.runLogsExited", { code: runStatus?.exit_code ?? "" })
                  : t("startupConfig.runLogsStopped")}
            </span>
          </div>
          <div
            role="log"
            aria-live="polite"
            className="max-h-80 overflow-auto px-4 py-3 font-mono text-[11px] leading-relaxed"
          >
            {runLogs.length === 0 ? (
              <p className="text-text-muted">{t("startupConfig.runLogsWaiting")}</p>
            ) : (
              runLogs.map((entry) => (
                <div
                  key={entry.seq}
                  className={cn(
                    "whitespace-pre-wrap break-all",
                    entry.stream === "stderr" ? "text-status-failed" : "text-text-secondary",
                  )}
                >
                  {entry.line}
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </section>
      )}
    </>
  );
}
