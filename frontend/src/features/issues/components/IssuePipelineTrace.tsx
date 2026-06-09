"use client";

import { useEffect, useState } from "react";
import {
  BarChart3,
  LayoutGrid,
  Code2,
  ShieldCheck,
  Check,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getIssuePipelineStages,
  type PipelineStage,
  type PipelineStagesResponse,
} from "@/lib/api";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";

interface Props {
  issueId: string;
  reloadKey?: string | number;
}

const ROLE_ICON: Record<string, LucideIcon> = {
  product_manager: BarChart3,
  architect: LayoutGrid,
  engineer: Code2,
  qa: ShieldCheck,
};

/**
 * Horizontal 4-station pipeline trace shown above the issue tabs.
 *
 * One station per role (PM / Architect / Engineer / QA). Stations
 * render in a fixed order even when the backend graph hasn't been
 * materialized yet — the empty stations stay grayed-out as "pending"
 * so the user always sees the full pipeline shape.
 */
export function IssuePipelineTrace({ issueId, reloadKey }: Props) {
  const { t } = useI18n();
  const [data, setData] = useState<PipelineStagesResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const next = await getIssuePipelineStages(issueId);
      if (!cancelled) setData(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [issueId, reloadKey]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn(
        "issue_updated",
        "task_status",
        "workflow_node_updated",
      ),
    ),
    onEvent: () => {
      void (async () => {
        const next = await getIssuePipelineStages(issueId);
        setData(next);
      })();
    },
    throttleMs: 500,
  });

  const stages = data?.stages ?? defaultStages();
  const isAllDone =
    stages.length > 0 && stages.every((s) => s.status === "done");

  return (
    <section
      className={cn(
        "enterprise-panel relative overflow-hidden rounded-[26px]",
        "px-5 pt-5 pb-4",
      )}
      style={{
        background:
          "linear-gradient(180deg, color-mix(in srgb, var(--color-surface-raised) 92%, white 8%) 0%, var(--color-surface) 100%)",
      }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(rgba(255,255,255,0.045) 1px, transparent 1px)",
          backgroundSize: "18px 18px",
          maskImage:
            "radial-gradient(ellipse 90% 100% at 50% 50%, #000 30%, transparent 80%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 90% 100% at 50% 50%, #000 30%, transparent 80%)",
        }}
      />
      <header className="relative flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center rounded-full border border-brand/20 bg-brand/10 px-2 py-0.5 font-mono text-[10.5px] uppercase tracking-[0.12em] text-brand font-semibold">
            {t("issue.trace.pipelineAgents", { n: String(stages.length) })}
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[11.5px] text-text-muted">
          {data?.started_at && (
            <>
              <span>
                {t("issue.trace.startedAt")}{" "}
                <b className="text-text-secondary font-medium">
                  {fmtTime(data.started_at)}
                </b>
              </span>
              <span className="text-text-faint">→</span>
              <span>
                {data.completed_at ? (
                  <>
                    {t("issue.trace.completedAt")}{" "}
                    <b className="text-text-secondary font-medium">
                      {fmtTime(data.completed_at)}
                    </b>
                  </>
                ) : (
                  <span className="text-status-running">
                    {t("issue.trace.runningNow")}
                  </span>
                )}
              </span>
              {data.total_duration_seconds != null && (
                <>
                  <span className="text-text-faint">·</span>
                  <span className="text-text-secondary">
                    {fmtDuration(data.total_duration_seconds)}
                  </span>
                </>
              )}
            </>
          )}
        </div>
      </header>

      <div className="relative grid grid-cols-2 sm:grid-cols-4 gap-y-6">
        {/* Connecting rail: spans from the first station icon's center to
            the last one's. Anchoring at 12.5%/87.5% (= 1st/4th column
            center on a 4-col grid) keeps the line strictly between
            stations — no tail past QA or before PM. */}
        <div
          aria-hidden
          className="hidden sm:block absolute left-[12.5%] right-[12.5%] top-[30px] h-px"
          style={{
            background: isAllDone
              ? "var(--color-done-ring)"
              : "var(--color-border-muted)",
          }}
        />
        <div
          aria-hidden
          className="hidden sm:block absolute left-[12.5%] right-[12.5%] top-[30px] h-px opacity-35 pointer-events-none"
          style={{
            backgroundImage: `linear-gradient(90deg, ${
              isAllDone
                ? "var(--color-status-done)"
                : "var(--color-text-muted)"
            } 50%, transparent 50%)`,
            backgroundSize: "8px 1px",
          }}
        />
        {stages.map((stage) => (
          <Station key={stage.role} stage={stage} t={t} />
        ))}
      </div>
    </section>
  );
}

function Station({
  stage,
  t,
}: {
  stage: PipelineStage;
  t: (key: string, params?: Record<string, string>) => string;
}) {
  const Icon = ROLE_ICON[stage.role] ?? BarChart3;
  const tone = stationTone(stage.status);
  const isRunningStage = stage.status === "running";

  return (
    <div className="relative px-3.5 flex flex-col items-center text-center min-w-0">
      <div
        data-density={isRunningStage ? "issue-pipeline-running-stage" : "issue-pipeline-stage"}
        className={cn(
          // bg-surface-raised covers the connecting rail line so it
          // doesn't visually cut through the icon tile.
          "relative w-[60px] h-[60px] overflow-hidden rounded-2xl flex items-center justify-center mb-3.5 z-[1] shadow-[0_10px_24px_-20px_rgba(0,0,0,0.75)]",
          "border bg-surface-raised",
          tone.nodeBorder,
          tone.nodeBg,
          tone.nodeText,
          isRunningStage && "motion-essential bg-status-running/10",
        )}
        style={tone.nodeShadow ? { boxShadow: tone.nodeShadow } : undefined}
      >
        {isRunningStage && (
          <span
            className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-running/70 to-transparent"
            aria-hidden
          />
        )}
        <Icon size={22} strokeWidth={1.8} />
        {stage.status === "done" && (
          <span
            className="absolute -top-1 -right-1 size-[18px] rounded-full bg-status-done flex items-center justify-center border-2 z-[2]"
            style={{ borderColor: "var(--color-surface)" }}
          >
            <Check size={10} strokeWidth={3.5} color="#06140b" />
          </span>
        )}
        {isRunningStage && (
          <span
            className="absolute -top-1 -right-1 flex size-[18px] items-center justify-center rounded-full border-2 bg-surface z-[2]"
            style={{ borderColor: "var(--color-surface)" }}
          >
            <AgentThinkingIndicator phase="dispatching" size={12} />
          </span>
        )}
        {stage.status === "failed" && (
          <span
            className="absolute -top-1 -right-1 size-[18px] rounded-full bg-status-failed flex items-center justify-center border-2 text-white text-[10px] font-bold z-[2]"
            style={{ borderColor: "var(--color-surface)" }}
          >
            !
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 mb-1.5">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-text-secondary font-semibold">
          {stage.label}
        </span>
        {(stage.started_at || stage.completed_at) && (
          <span className="font-mono text-[11px] text-text-faint">
            {stage.started_at ? fmtTime(stage.started_at) : "—"}
            {stage.completed_at && (
              <>
                {" → "}
                {fmtTime(stage.completed_at)}
              </>
            )}
          </span>
        )}
      </div>

      <div className="text-[14.5px] leading-snug text-foreground font-medium max-w-[200px] text-balance">
        {stage.summary || labelFallback(stage.status, t)}
      </div>

      {stage.foot && (
        <div className="mt-2 font-mono text-[11px] text-text-muted flex items-center gap-1.5">
          {stage.foot}
        </div>
      )}
    </div>
  );
}

function stationTone(status: string): {
  nodeBorder: string;
  nodeBg: string;
  nodeText: string;
  nodeShadow?: string;
} {
  switch (status) {
    case "done":
      return {
        nodeBorder: "",
        nodeBg: "",
        nodeText: "text-status-done",
        nodeShadow:
          "0 0 0 1px var(--color-done-ring) inset, 0 8px 24px -10px color-mix(in srgb, var(--color-status-done) 40%, transparent)",
      };
    case "running":
      return {
        nodeBorder: "",
        nodeBg: "",
        nodeText: "text-status-running",
        nodeShadow:
          "0 0 0 1px var(--color-brand-ring) inset, 0 8px 24px -10px var(--color-brand-ring)",
      };
    case "failed":
      return {
        nodeBorder: "",
        nodeBg: "",
        nodeText: "text-status-failed",
        nodeShadow:
          "0 0 0 1px var(--color-failed-ring) inset, 0 8px 24px -10px color-mix(in srgb, var(--color-status-failed) 40%, transparent)",
      };
    case "awaiting":
      return {
        nodeBorder: "border-status-awaiting/40",
        nodeBg: "bg-surface-raised",
        nodeText: "text-status-awaiting",
      };
    default:
      return {
        nodeBorder: "border-border-muted",
        nodeBg: "bg-surface-raised",
        nodeText: "text-text-muted",
      };
  }
}

function labelFallback(
  status: string,
  t: (key: string) => string,
): string {
  if (status === "running") return t("issue.trace.stageRunning");
  if (status === "failed") return t("issue.trace.stageFailed");
  if (status === "awaiting") return t("issue.trace.stageAwaiting");
  return t("issue.trace.stagePending");
}

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch {
    return "—";
  }
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return s ? `${m}m ${String(s).padStart(2, "0")}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function defaultStages(): PipelineStage[] {
  return [
    {
      role: "product_manager",
      label: "PM",
      status: "pending",
      started_at: null,
      completed_at: null,
      duration_seconds: null,
      summary: "",
      foot: "",
      task_id: null,
    },
    {
      role: "architect",
      label: "Architect",
      status: "pending",
      started_at: null,
      completed_at: null,
      duration_seconds: null,
      summary: "",
      foot: "",
      task_id: null,
    },
    {
      role: "engineer",
      label: "Engineer",
      status: "pending",
      started_at: null,
      completed_at: null,
      duration_seconds: null,
      summary: "",
      foot: "",
      task_id: null,
    },
    {
      role: "qa",
      label: "QA",
      status: "pending",
      started_at: null,
      completed_at: null,
      duration_seconds: null,
      summary: "",
      foot: "",
      task_id: null,
    },
  ];
}
