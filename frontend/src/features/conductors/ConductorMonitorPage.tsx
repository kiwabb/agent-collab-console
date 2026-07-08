"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertCircle, AlertTriangle, CheckCircle2, Pause, RefreshCw } from "lucide-react";

import { getConductors, type ConductorSession } from "@/lib/api/projects";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { PageFrame } from "@/features/workbench/components/PageFrame";
import { useI18n } from "@/providers/I18nProvider";
import { formatDuration } from "@/features/issues/components/StatusStrip";

const HEALTH_STYLE: Record<
  ConductorSession["health"],
  { dot: string; label: string; icon: typeof CheckCircle2 }
> = {
  ok: { dot: "text-status-done", label: "issue.command.status.running", icon: CheckCircle2 },
  warn: { dot: "text-status-awaiting", label: "conductorMonitor.health.warn", icon: AlertTriangle },
  danger: {
    dot: "text-status-failed",
    label: "conductorMonitor.health.danger",
    icon: AlertTriangle,
  },
  stalled: {
    dot: "text-status-failed",
    label: "conductorMonitor.health.stalled",
    icon: AlertCircle,
  },
  failed: { dot: "text-status-failed", label: "conductorMonitor.health.failed", icon: AlertCircle },
  paused: { dot: "text-text-muted", label: "conductorMonitor.health.paused", icon: Pause },
};

export function ConductorMonitorPage() {
  const router = useRouter();
  const { t } = useI18n();
  const [sessions, setSessions] = useState<ConductorSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (showRefreshing = false) => {
    if (showRefreshing) setRefreshing(true);
    try {
      setSessions(await getConductors().catch(() => []));
    } finally {
      setLoading(false);
      if (showRefreshing) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(id);
  }, [load]);

  useBusEventEffect({
    match: busEventMatchers.typeIn("conductor_status", "conductor_failed", "conductor_turn"),
    onEvent: () => {
      void load();
    },
    throttleMs: 1000,
  });

  const problems = sessions.filter((s) =>
    ["failed", "stalled", "danger", "warn"].includes(s.health),
  ).length;

  return (
    <PageFrame
      eyebrow={t("conductorMonitor.eyebrow")}
      title={t("conductorMonitor.title")}
      description={t("conductorMonitor.description")}
      actions={
        <Button
          size="sm"
          variant="outline"
          onClick={() => void load(true)}
          disabled={refreshing}
          data-density={refreshing ? "conductor-monitor-refresh-tool" : "conductor-monitor-refresh"}
          className={cn("gap-2", refreshing && "motion-essential")}
        >
          {refreshing ? <AgentThinkingIndicator phase="tool" size={14} /> : <RefreshCw size={14} />}
          {t("conductorMonitor.refresh")}
        </Button>
      }
      contentClassName="space-y-4"
    >
      {problems > 0 && (
        <div className="rounded-2xl border border-status-failed/30 bg-status-failed/10 px-4 py-3 text-sm font-semibold text-status-failed">
          {t("conductorMonitor.problemBanner", { count: problems })}
        </div>
      )}

      {loading ? (
        <div
          data-density="conductor-monitor-loading"
          className="motion-essential relative flex items-center gap-2 overflow-hidden rounded-2xl border border-brand/25 bg-brand-muted/10 px-6 py-12 text-sm text-text-muted"
        >
          <span
            aria-hidden
            className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
          />
          <AgentThinkingIndicator phase="thinking" size={15} /> {t("conductorMonitor.loading")}
        </div>
      ) : sessions.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border-subtle bg-surface-input/40 px-6 py-12 text-center text-sm text-text-muted">
          {t("conductorMonitor.empty")}
        </div>
      ) : (
        <ul className="space-y-2">
          {sessions.map((s) => {
            const style = HEALTH_STYLE[s.health] ?? HEALTH_STYLE.ok;
            const Icon = style.icon;
            const isConductorDispatching = s.status === "running" && s.alive && s.health === "ok";
            return (
              <li key={s.conductor_task_id}>
                <button
                  type="button"
                  data-density="conductor-monitor-row"
                  onClick={() => router.push(`/issues/${s.issue_id}`)}
                  className={cn(
                    "relative grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 overflow-hidden rounded-2xl border bg-surface-raised/70 p-4 text-left transition-colors hover:border-brand/50",
                    (s.health === "failed" || s.health === "stalled" || s.health === "danger") &&
                      "border-status-failed/30 bg-status-failed/5",
                    s.health === "warn" && "border-status-awaiting/30 bg-status-awaiting/5",
                    s.health === "ok" && "border-border-subtle",
                    s.health === "paused" && "border-border-subtle",
                    isConductorDispatching && "motion-essential border-brand/35 bg-brand-muted/10",
                  )}
                >
                  {isConductorDispatching && (
                    <span
                      aria-hidden
                      className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
                    />
                  )}
                  <span
                    className={cn(
                      "inline-flex size-9 items-center justify-center rounded-xl border border-border-subtle bg-surface",
                      style.dot,
                    )}
                  >
                    {isConductorDispatching ? (
                      <AgentThinkingIndicator phase={s.phase ?? "dispatching"} size={16} />
                    ) : (
                      <Icon size={17} />
                    )}
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-bold text-foreground">
                        {s.issue_title || t("conductorMonitor.untitled")}
                      </h3>
                      <span
                        className={cn(
                          "rounded-full border border-border-subtle px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                          style.dot,
                        )}
                      >
                        {t(style.label)}
                      </span>
                      {!s.alive && s.status === "running" && (
                        <span className="rounded-full border border-status-failed/30 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-status-failed">
                          {t("conductorMonitor.notAlive")}
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-xs text-text-muted">
                      <span>#{s.issue_id.slice(0, 8)}</span>
                      <span>·</span>
                      <span>{s.phase || s.status}</span>
                      {s.detail && <span className="text-text-secondary">{s.detail}</span>}
                    </div>
                  </div>
                  <div className="text-right font-mono text-xs text-text-secondary">
                    {s.phase_duration_ms != null ? formatDuration(s.phase_duration_ms) : "—"}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </PageFrame>
  );
}
