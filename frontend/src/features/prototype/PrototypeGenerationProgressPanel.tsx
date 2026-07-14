"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock3,
  Code2,
  FileClock,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { PrototypeGenerationRun, PrototypePlanOutputLocale } from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  derivePrototypeGenerationProgress,
  formatPrototypeElapsed,
  isPrototypeGenerationRunActive,
  prototypeGenerationErrorMessage,
} from "./prototypePlanReviewState";
import type { PrototypeGenerationConnectionIssue } from "./usePrototypeGenerationLiveRun";

interface Props {
  run: PrototypeGenerationRun;
  locale: PrototypePlanOutputLocale;
  t: (key: string, params?: Record<string, string | number>) => string;
  actionError: string | null;
  connectionIssue: PrototypeGenerationConnectionIssue | null;
  pollingError: string | null;
  usingPollingFallback: boolean;
  isRetrying: boolean;
  isRefreshing: boolean;
  onRetry: () => void;
  onRefresh: () => void;
}

const ITEM_STATUS_KEYS: Record<PrototypeGenerationRun["items"][number]["status"], string> = {
  pending: "prototype.plan.generationPending",
  generating: "prototype.plan.generationGenerating",
  done: "prototype.plan.generationDone",
  failed: "prototype.plan.generationFailed",
  interrupted: "prototype.plan.generationInterrupted",
  skipped: "prototype.plan.generationSkipped",
};

function itemBadgeVariant(status: PrototypeGenerationRun["items"][number]["status"]) {
  if (status === "failed" || status === "interrupted") return "destructive" as const;
  if (status === "done") return "secondary" as const;
  return "outline" as const;
}

function errorLabel(
  message: string,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  const localized = prototypeGenerationErrorMessage(message);
  return t(localized.key, localized.params);
}

export function PrototypeGenerationProgressPanel({
  run,
  locale,
  t,
  actionError,
  connectionIssue,
  pollingError,
  usingPollingFallback,
  isRetrying,
  isRefreshing,
  onRetry,
  onRefresh,
}: Props) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const active = isPrototypeGenerationRunActive(run);
  const progress = useMemo(() => derivePrototypeGenerationProgress(run), [run]);

  useEffect(() => {
    if (!active) return;
    const interval = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [active]);

  const elapsed = formatPrototypeElapsed(run.started_at ?? run.created_at, run.completed_at, nowMs);
  const lastActivity = progress.latestEventAt
    ? new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(progress.latestEventAt))
    : t("prototype.plan.generationNoActivity");
  const canRetry =
    progress.failedItems.length > 0 &&
    (run.status === "partial" || run.status === "failed" || run.status === "interrupted");

  return (
    <section
      className="overflow-hidden rounded-lg border border-border-subtle bg-surface-raised/70"
      data-density="compact"
    >
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border-subtle px-3 py-2 sm:gap-3 sm:px-4 sm:py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {active ? (
              <Loader2
                className="motion-essential shrink-0 animate-spin text-brand"
                size={17}
                aria-hidden="true"
              />
            ) : (
              <Activity className="shrink-0 text-brand" size={17} aria-hidden="true" />
            )}
            <h2 className="text-sm font-semibold">{t("prototype.plan.generationProgressTitle")}</h2>
            <Badge variant="outline">{t(`prototype.plan.generationRun.${run.status}`)}</Badge>
          </div>
          <p
            role="status"
            aria-live="polite"
            aria-atomic="true"
            className="mt-0.5 text-xs text-text-muted sm:mt-1"
          >
            {t("prototype.plan.generationProcessed", {
              processed: progress.processed,
              total: progress.total,
            })}
          </p>
        </div>
        {canRetry && (
          <Button
            className="min-h-11"
            size="sm"
            variant="outline"
            onClick={onRetry}
            disabled={isRetrying}
          >
            <RefreshCw className={cn(isRetrying && "animate-spin")} size={14} />
            {t("prototype.plan.retryFailed")}
          </Button>
        )}
      </div>

      <div className="px-3 py-2 sm:px-4 sm:py-3">
        {run.error_message && (
          <div
            role="alert"
            className="mb-3 border-l-2 border-status-failed px-3 py-2 text-xs text-status-failed [overflow-wrap:anywhere]"
          >
            {errorLabel(run.error_message, t)}
          </div>
        )}
        <div
          className="h-1.5 overflow-hidden rounded-sm bg-surface-base sm:h-2"
          role="progressbar"
          aria-label={t("prototype.plan.generationProgressTitle")}
          aria-valuemin={0}
          aria-valuemax={Math.max(progress.total, 1)}
          aria-valuenow={progress.processed}
          aria-valuetext={t("prototype.plan.generationProcessed", {
            processed: progress.processed,
            total: progress.total,
          })}
        >
          <div className="h-full bg-brand" style={{ width: `${progress.percent}%` }} />
        </div>

        <dl className="mt-2 grid grid-cols-3 divide-x divide-y divide-border-subtle border border-border-subtle sm:mt-3 lg:grid-cols-6 lg:divide-y-0">
          {[
            ["prototype.plan.generationMetricProcessed", `${progress.processed}/${progress.total}`],
            ["prototype.plan.generationMetricSucceeded", progress.succeeded],
            ["prototype.plan.generationMetricFailed", progress.failed],
            ["prototype.plan.generationMetricRunning", progress.running],
            ["prototype.plan.generationMetricPending", progress.pending],
            ["prototype.plan.generationMetricElapsed", elapsed],
          ].map(([label, value]) => (
            <div key={label} className="min-w-0 px-2 py-1.5 sm:px-3 sm:py-2.5">
              <dt className="text-[12px] text-text-muted">{t(String(label))}</dt>
              <dd className="mt-0.5 break-words font-mono text-sm font-semibold tabular-nums sm:text-base">
                {value}
              </dd>
            </div>
          ))}
        </dl>

        <div className="flex flex-col">
          {progress.failedItems.length > 0 && (
            <div className="order-1 mt-2 border-t border-status-failed/30 pt-2 sm:order-2 sm:mt-3 sm:pt-3">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-status-failed">
                <XCircle size={14} aria-hidden="true" />
                {t("prototype.plan.generationFailureSummary", {
                  count: progress.failedItems.length,
                })}
              </div>
              <ul className="mt-1 space-y-0.5 text-xs sm:mt-2 sm:space-y-1.5">
                {progress.failedItems.map((item) => (
                  <li
                    key={item.id}
                    className="min-w-0 border-l-2 border-status-failed/40 pl-2 leading-tight sm:leading-normal"
                  >
                    <span className="break-words font-medium">
                      {item.title || item.plan_item_id}
                    </span>
                    <span className="ml-1 text-status-failed [overflow-wrap:anywhere]">
                      {item.error_message
                        ? errorLabel(item.error_message, t)
                        : item.status_message || t(ITEM_STATUS_KEYS[item.status])}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="order-2 mt-2 grid grid-cols-2 gap-2 border-t border-border-subtle pt-2 sm:order-1 sm:mt-3 sm:gap-3 sm:pt-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-xs font-semibold">
                <FileClock size={14} aria-hidden="true" />
                {t("prototype.plan.generationCurrentPages")}
              </div>
              {progress.currentItems.length > 0 ? (
                <>
                  <ul className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 sm:hidden">
                    {progress.currentItems.map((item) => (
                      <li key={item.id} className="min-w-0 break-words text-xs">
                        <span className="font-medium">{item.title || item.plan_item_id}</span>
                        <span className="text-text-muted">
                          {" · "}
                          {t(`prototype.plan.generationPhase.${item.phase}`)}
                        </span>
                      </li>
                    ))}
                  </ul>
                  <ul className="mt-2 hidden space-y-1.5 sm:block">
                    {progress.currentItems.map((item) => (
                      <li key={item.id} className="min-w-0 text-xs">
                        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                          <span className="break-words font-medium">
                            {item.title || item.plan_item_id}
                          </span>
                          <Badge variant="outline">
                            {t(`prototype.plan.generationPhase.${item.phase}`)}
                          </Badge>
                        </div>
                        <div className="mt-0.5 break-words text-text-muted">
                          {item.status_message ||
                            t("prototype.plan.generationOutputChars", { count: item.output_chars })}
                        </div>
                        {item.task_id && (
                          <div className="mt-1.5 border-l-2 border-brand/50 pl-2 text-text-muted">
                            <div className="flex items-center gap-1 font-medium text-foreground">
                              <Code2 size={12} aria-hidden="true" />
                              {t("prototype.plan.generationUiEngineer")}
                            </div>
                            <details className="mt-0.5">
                              <summary className="flex min-h-11 cursor-pointer items-center text-xs">
                                {t("prototype.plan.generationCorrelation")}
                              </summary>
                              <div className="space-y-0.5 break-all font-mono text-[12px]">
                                <div>
                                  {t("prototype.plan.generationTaskId", { id: item.task_id })}
                                </div>
                                {item.execution_process_id && (
                                  <div>
                                    {t("prototype.plan.generationProcessId", {
                                      id: item.execution_process_id,
                                    })}
                                  </div>
                                )}
                              </div>
                            </details>
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="mt-1 text-xs text-text-muted sm:mt-2">
                  {active
                    ? t("prototype.plan.generationWaitingForPage")
                    : t("prototype.plan.generationNoCurrentPage")}
                </p>
              )}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-xs font-semibold">
                <Clock3 size={14} aria-hidden="true" />
                {t("prototype.plan.generationOutputActivity")}
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-xs text-text-muted sm:mt-2 sm:gap-x-4 sm:gap-y-1">
                <span>
                  {t("prototype.plan.generationOutputChars", {
                    count: progress.totalOutputChars.toLocaleString(locale),
                  })}
                </span>
                <span>{t("prototype.plan.generationLastActivity", { time: lastActivity })}</span>
              </div>
            </div>
          </div>
        </div>

        {(connectionIssue || usingPollingFallback) && (
          <div
            role={connectionIssue && connectionIssue !== "silent" ? "alert" : "status"}
            aria-live="polite"
            className="mt-3 flex flex-wrap items-center justify-between gap-2 border-l-2 border-status-awaiting px-3 py-2 text-xs text-status-awaiting"
          >
            <span className="min-w-0 break-words">
              {t(
                connectionIssue === "invalid_snapshot"
                  ? "prototype.plan.generationSnapshotFailed"
                  : connectionIssue === "disconnected"
                    ? "prototype.plan.generationStreamFailed"
                    : "prototype.plan.generationStreamSilent",
              )}
              {usingPollingFallback && (
                <span className="ml-1">{t("prototype.plan.generationPollingFallback")}</span>
              )}
            </span>
            <Button
              className="min-h-11"
              size="sm"
              variant="outline"
              onClick={onRefresh}
              disabled={isRefreshing}
            >
              <RefreshCw className={cn(isRefreshing && "animate-spin")} size={14} />
              {t("prototype.plan.generationReconcileNow")}
            </Button>
          </div>
        )}
        {(actionError || pollingError) && (
          <div
            role="alert"
            className="mt-3 flex flex-wrap items-center justify-between gap-2 border-l-2 border-status-failed px-3 py-2 text-xs text-status-failed"
          >
            <span className="min-w-0 break-words">
              {actionError ? errorLabel(actionError, t) : errorLabel(pollingError ?? "", t)}
            </span>
            <Button
              className="min-h-11"
              size="sm"
              variant="outline"
              onClick={onRefresh}
              disabled={isRefreshing}
            >
              <RefreshCw className={cn(isRefreshing && "animate-spin")} size={14} />
              {t("prototype.plan.generationReconcileNow")}
            </Button>
          </div>
        )}

        <details className="mt-3 border-t border-border-subtle pt-3">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 text-xs font-semibold marker:hidden">
            {run.status === "completed" ? (
              <CheckCircle2 size={14} aria-hidden="true" />
            ) : (
              <Activity size={14} aria-hidden="true" />
            )}
            {t("prototype.plan.generationPageDetails", { count: run.items.length })}
          </summary>
          <ul className="divide-y divide-border-subtle border-y border-border-subtle">
            {run.items.map((item) => (
              <li
                key={item.id}
                className="flex min-w-0 flex-col gap-1.5 py-2 text-xs sm:flex-row sm:items-start sm:justify-between"
              >
                <div className="min-w-0">
                  <div className="break-words font-medium">{item.title || item.plan_item_id}</div>
                  <div className="mt-0.5 break-words text-text-muted">
                    {t(`prototype.plan.generationPhase.${item.phase}`)}
                    {item.output_chars > 0
                      ? ` · ${t("prototype.plan.generationOutputChars", { count: item.output_chars })}`
                      : ""}
                  </div>
                  {item.task_id && (
                    <div className="mt-1 break-all font-mono text-[12px] text-text-muted">
                      <span className="font-sans font-medium text-foreground">
                        {t("prototype.plan.generationUiEngineer")}
                      </span>{" "}
                      · {t("prototype.plan.generationTaskId", { id: item.task_id })}
                      {item.execution_process_id
                        ? ` · ${t("prototype.plan.generationProcessId", {
                            id: item.execution_process_id,
                          })}`
                        : ""}
                    </div>
                  )}
                  {item.error_message && (
                    <div className="mt-1 break-words text-status-failed">
                      {errorLabel(item.error_message, t)}
                    </div>
                  )}
                </div>
                <Badge className="shrink-0 self-start" variant={itemBadgeVariant(item.status)}>
                  {t(ITEM_STATUS_KEYS[item.status])}
                </Badge>
              </li>
            ))}
          </ul>
        </details>
      </div>
    </section>
  );
}
