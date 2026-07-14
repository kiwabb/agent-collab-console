"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ExternalLink, FileCode2, Play, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  getProjectServiceRunLogs,
  getProjectServiceRunStatus,
  startProjectServiceRun,
  stopProjectServiceRun,
} from "@/lib/api/projects";
import type { ProjectRunLogLine, ProjectRunStatus, ProjectStartupService } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  projectId: string;
  service: ProjectStartupService;
  disabled: boolean;
}

export function ProjectStartupServicePanel({ projectId, service, disabled }: Props) {
  const { t } = useI18n();
  const [status, setStatus] = useState<ProjectRunStatus | null>(null);
  const [logs, setLogs] = useState<ProjectRunLogLine[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastSeqRef = useRef(0);

  const refresh = useCallback(async () => {
    try {
      const nextStatus = await getProjectServiceRunStatus(projectId, service.service_id);
      setStatus(nextStatus);
      if (nextStatus.running) {
        const nextLogs = await getProjectServiceRunLogs(
          projectId,
          service.service_id,
          lastSeqRef.current,
        );
        if (nextLogs.lines.length > 0) {
          lastSeqRef.current = nextLogs.last_seq;
          setLogs((current) => [...current, ...nextLogs.lines]);
        }
      }
      setError(null);
    } catch (err) {
      console.error("startup service refresh failed", err);
      setError(err instanceof Error ? err.message : t("startupConfig.loadFailed"));
    }
  }, [projectId, service.service_id, t]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, status?.running ? 2_000 : 5_000);
    return () => window.clearInterval(timer);
  }, [refresh, status?.running]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      setLogs([]);
      lastSeqRef.current = 0;
      setStatus(await startProjectServiceRun(projectId, service.service_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("projects.runStartFailed"));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await stopProjectServiceRun(projectId, service.service_id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("projects.runStopFailed"));
    } finally {
      setBusy(false);
    }
  };

  const reachable = status?.service.state === "reachable";
  const stateLabel = status?.running
    ? t("startupConfig.runLogsRunning")
    : reachable
      ? t("startupConfig.serviceState.reachable")
      : t("startupConfig.serviceState.offline");

  return (
    <article className="overflow-hidden rounded-lg border border-border-subtle bg-surface-raised">
      <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-sm font-semibold">{service.name}</h4>
            <span className="rounded border border-border-subtle px-2 py-0.5 font-mono text-[11px] text-text-muted">
              {service.service_id}
            </span>
            <span
              className={cn(
                "text-xs font-semibold",
                status?.running || reachable ? "text-status-done" : "text-text-muted",
              )}
            >
              {stateLabel}
            </span>
          </div>
          <p className="mt-2 font-mono text-xs text-text-muted">{service.working_directory}</p>
          <pre className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-5">
            {service.run_command}
          </pre>
          {service.depends_on.length > 0 && (
            <p className="mt-2 text-xs text-text-muted">
              {t("startupConfig.dependsOn", { services: service.depends_on.join(", ") })}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {service.access_url && (
            <a
              href={service.access_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex size-9 items-center justify-center rounded-md border border-border-subtle text-brand hover:bg-surface-hover"
              title={t("startupConfig.openService")}
            >
              <ExternalLink size={15} />
            </a>
          )}
          {status?.running ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => void stop()}
              disabled={busy || disabled}
            >
              <Square size={14} />
              {t("projects.runStop")}
            </Button>
          ) : reachable ? null : (
            <Button size="sm" onClick={() => void start()} disabled={busy || disabled}>
              <Play size={14} />
              {t("projects.runStart")}
            </Button>
          )}
        </div>
      </div>

      {error && (
        <p
          role="alert"
          className="border-t border-status-failed/30 px-4 py-3 text-xs text-status-failed"
        >
          {error}
        </p>
      )}

      <div className="border-t border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-muted">
          <FileCode2 size={14} />
          {t("startupConfig.evidence")}
        </div>
        <p className="mt-1 break-words text-xs text-text-muted">{service.evidence.join(", ")}</p>
      </div>

      {(status?.running || logs.length > 0) && (
        <div
          role="log"
          className="max-h-64 overflow-auto border-t border-border-subtle bg-black/90 px-4 py-3 font-mono text-[11px] leading-5"
        >
          {logs.length === 0 ? (
            <p className="text-text-muted">{t("startupConfig.runLogsWaiting")}</p>
          ) : (
            logs.map((entry) => (
              <div
                key={entry.seq}
                className={entry.stream === "stderr" ? "text-status-failed" : "text-text-secondary"}
              >
                {entry.line}
              </div>
            ))
          )}
        </div>
      )}
    </article>
  );
}
