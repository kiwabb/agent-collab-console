"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getCodexCostStats,
  getCodexTasks,
  getIssueGraphStats,
  getIssuePipelineStages,
  type CodexCostStats,
  type GraphNodeStat,
  type GraphStatsResponse,
  type PipelineStagesResponse,
  type PipelineStage,
} from "@/lib/api";
import {
  BarChart3,
  LayoutGrid,
  Code2,
  ShieldCheck,
  AudioWaveform,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import type { CodexTask } from "@/lib/types";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";

interface Props {
  issueId: string;
}

/**
 * Always-visible top strip on the Tasks·Runs tab — mirrors the design
 * handoff's runs-toolbar + gantt. Renders task count, cost summary, a
 * time axis, and one Gantt bar per role (PM / Architect / Engineer / QA).
 *
 * Bars are positioned by the per-stage started_at/completed_at percentages
 * relative to the pipeline's overall window — same calculation the design
 * mock used in its inline comments.
 */
export function TasksOverviewBar({ issueId }: Props) {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<CodexTask[]>([]);
  const [cost, setCost] = useState<CodexCostStats | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStagesResponse | null>(null);
  const [graphStats, setGraphStats] = useState<GraphStatsResponse | null>(null);

  const refresh = useCallback(async () => {
    const [tk, c, p, gs] = await Promise.all([
      getCodexTasks(null, issueId).catch(() => [] as CodexTask[]),
      getCodexCostStats({ issueId }).catch(() => null),
      getIssuePipelineStages(issueId).catch(() => null),
      getIssueGraphStats(issueId).catch(() => null),
    ]);
    setTasks(tk);
    setCost(c);
    setPipeline(p);
    setGraphStats(gs);
  }, [issueId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn(
        "task_status",
        "task_created",
        "workflow_node_updated",
      ),
    ),
    onEvent: () => {
      void refresh();
    },
    throttleMs: 600,
  });

  const { startMs, durationMs } = useMemo(() => {
    const starts: number[] = [];
    const ends: number[] = [];
    if (pipeline?.started_at)
      starts.push(new Date(pipeline.started_at).getTime());
    if (pipeline?.completed_at)
      ends.push(new Date(pipeline.completed_at).getTime());
    for (const s of pipeline?.stages ?? []) {
      if (s.started_at) starts.push(new Date(s.started_at).getTime());
      if (s.completed_at) ends.push(new Date(s.completed_at).getTime());
    }
    for (const t of tasks) {
      if (t.created_at) starts.push(new Date(t.created_at).getTime());
      if (t.updated_at) ends.push(new Date(t.updated_at).getTime());
    }
    const start = starts.length ? Math.min(...starts) : null;
    const end = ends.length ? Math.max(...ends) : start;
    return {
      startMs: start,
      endMs: end,
      durationMs: start != null && end != null ? Math.max(end - start, 1) : 0,
    };
  }, [pipeline, tasks]);

  const counts = useMemo(() => {
    let done = 0;
    let running = 0;
    for (const t of tasks) {
      const s = (t.status ?? "").toLowerCase();
      if (s === "done") done += 1;
      else if (s === "running" || s === "in_progress") running += 1;
    }
    return { total: tasks.length, done, running };
  }, [tasks]);

  const stages = pipeline?.stages ?? [];

  return (
    <div className="shrink-0 border-b border-border-subtle bg-surface/86 backdrop-blur-sm">
      <div className="flex items-center justify-between gap-3.5 px-4 py-3 font-mono text-[12px] text-text-muted flex-wrap">
        <div className="flex items-center gap-3.5 flex-wrap">
          <span>
            <b className="text-foreground font-medium">{counts.total}</b>{" "}
            {t("issue.tasksOverview.tasksLabel")}
            <span className="text-text-faint"> · </span>
            <b className="text-foreground font-medium">{counts.done}</b>{" "}
            {t("issue.tasksOverview.doneLabel")}
            <span className="text-text-faint"> · </span>
            <b className="text-foreground font-medium">{counts.running}</b>{" "}
            {t("issue.tasksOverview.runningLabel")}
          </span>
          <span className="text-text-faint">·</span>
          <span>
            <b className="text-foreground font-medium">
              {formatNum(
                cost ? cost.input_tokens + cost.output_tokens : 0,
              )}
            </b>{" "}
            {t("issue.tasksOverview.tokensLabel")}
          </span>
          <span className="text-text-faint">·</span>
          <span>
            <b className="text-foreground font-medium">
              {cost ? `$${cost.est_cost_usd.toFixed(3)}` : "$0.000"}
            </b>
          </span>
          {pipeline?.total_duration_seconds != null && (
            <>
              <span className="text-text-faint">·</span>
              <span>
                <b className="text-foreground font-medium">
                  {fmtDuration(pipeline.total_duration_seconds)}
                </b>{" "}
                {t("issue.tasksOverview.wallLabel")}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Gantt */}
      <div
        className="px-4 py-3.5 border-t border-border-subtle bg-surface/40"
        style={{
          background:
            "linear-gradient(180deg, color-mix(in srgb, var(--color-surface-raised) 50%, transparent), transparent)",
        }}
      >
        <Axis startMs={startMs} durationMs={durationMs} />
        {stages.length === 0 ? (
          <div className="text-[11px] text-text-muted font-mono py-1.5">
            {t("issue.tasksOverview.ganttEmpty")}
          </div>
        ) : (
          stages.map((s) => (
            <GanttRow
              key={s.role}
              stage={s}
              startMs={startMs}
              durationMs={durationMs}
            />
          ))
        )}
      </div>

      {/* runs-list — per-role row mirroring design handoff */}
      {stages.length > 0 && (
        <div className="border-t border-border-subtle bg-surface/35">
          {graphStats?.conductor && (
            <RunsListRow
              role="conductor"
              label="Conductor"
              kind="start"
              summary={`conductor.plan(issue=${issueId.slice(0, 8)}, mode="auto") → ${stages.length} nodes`}
              startedAt={pipeline?.started_at ?? null}
              durationSeconds={null}
              stat={graphStats.conductor}
            />
          )}
          {stages.map((s) => {
            const stat = graphStats?.nodes?.[s.role];
            return (
              <RunsListRow
                key={s.role}
                role={s.role}
                label={s.label}
                kind={s.status === "running" || s.status === "awaiting" ? "start" : "done"}
                summary={s.summary || s.label}
                startedAt={s.started_at}
                durationSeconds={s.duration_seconds}
                stat={stat ?? null}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

const ROLE_ICON: Record<string, LucideIcon> = {
  conductor: AudioWaveform,
  product_manager: BarChart3,
  architect: LayoutGrid,
  engineer: Code2,
  qa: ShieldCheck,
};

const ROLE_DESC: Record<string, string> = {
  conductor: "auto-plan",
  product_manager: "需求分解",
  architect: "系统设计",
  engineer: "代码实现",
  qa: "验证",
};

function RunsListRow({
  role,
  label,
  kind,
  summary,
  startedAt,
  durationSeconds,
  stat,
}: {
  role: string;
  label: string;
  kind: "done" | "start";
  summary: string;
  startedAt: string | null;
  durationSeconds: number | null;
  stat: GraphNodeStat | null;
}) {
  const Icon = ROLE_ICON[role] ?? BarChart3;
  const desc = ROLE_DESC[role] ?? role;
  const dur =
    (stat?.duration_seconds ?? durationSeconds);

  return (
    <div
      className="grid grid-cols-[24px_140px_minmax(0,1fr)_90px_100px_80px_24px] items-center gap-3 px-4 py-2.5 border-b border-border-subtle last:border-b-0 hover:bg-surface-hover/60 transition-colors"
    >
      <span
        className="size-[18px] rounded-full flex items-center justify-center justify-self-center"
        style={{
          background:
            kind === "start"
              ? "var(--color-brand-bg)"
              : "var(--color-done-bg)",
          color:
            kind === "start"
              ? "var(--color-brand)"
              : "var(--color-status-done)",
        }}
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="5 12 10 17 19 7" />
        </svg>
      </span>
      <div className="flex items-center gap-2 min-w-0">
        <span
          className="size-6 shrink-0 rounded-md flex items-center justify-center"
          style={{
            background:
              kind === "start"
                ? "var(--color-brand-bg)"
                : "var(--color-done-bg)",
            color:
              kind === "start"
                ? "var(--color-brand)"
                : "var(--color-status-done)",
          }}
        >
          <Icon size={13} />
        </span>
        <div className="min-w-0">
          <div className="font-mono text-[11px] uppercase tracking-[0.08em] font-semibold text-foreground leading-tight">
            {label}
          </div>
          <div className="text-[11px] text-text-muted leading-tight mt-0.5">
            {desc}
          </div>
        </div>
      </div>
      <div className="font-mono text-[12px] text-text-secondary truncate">
        {summary}
      </div>
      <div className="font-mono text-[11.5px] text-text-secondary text-right">
        {dur != null ? fmtDuration(dur) : "—"}
        <small className="block text-[10px] text-text-faint mt-0.5">
          {fmtTimeOnly(startedAt)}
        </small>
      </div>
      <div className="font-mono text-[11.5px] text-text-secondary text-right">
        {stat?.tokens ? fmtTok(stat.tokens.total) : "—"}
        <small className="block text-[10px] text-text-faint mt-0.5">
          {stat?.tokens
            ? `${fmtTok(stat.tokens.input)} · ${fmtTok(stat.tokens.output)}`
            : "in · out"}
        </small>
      </div>
      <div className="font-mono text-[11.5px] text-text-secondary text-right">
        {stat?.est_cost_usd != null
          ? `$${stat.est_cost_usd.toFixed(3)}`
          : "—"}
      </div>
      <span className="text-text-faint justify-self-end">
        <ChevronRight size={12} />
      </span>
    </div>
  );
}

function fmtTimeOnly(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
  } catch {
    return "";
  }
}

function fmtTok(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function Axis({
  startMs,
  durationMs,
}: {
  startMs: number | null;
  durationMs: number;
}) {
  if (!startMs || durationMs <= 0) {
    return (
      <div className="relative h-[18px] mb-2 font-mono text-[10px] text-text-faint">
        <span>—</span>
      </div>
    );
  }
  const ticks = [0, 25, 50, 75, 100];
  return (
    <div className="relative h-[18px] mb-2 font-mono text-[10px] text-text-faint">
      {ticks.map((pct) => {
        const ts = startMs + (durationMs * pct) / 100;
        const left = `${pct}%`;
        const align =
          pct === 100
            ? { transform: "translateX(-100%)" }
            : pct === 0
              ? {}
              : { transform: "translateX(-0.5px)" };
        return (
          <div
            key={pct}
            className="absolute top-0 bottom-0 w-px bg-border-muted"
            style={{ left, ...align }}
          >
            <span
              className="absolute top-0 leading-[18px] whitespace-nowrap"
              style={{
                left: pct === 100 ? "auto" : "6px",
                right: pct === 100 ? "0px" : "auto",
              }}
            >
              {fmtTime(ts)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function GanttRow({
  stage,
  startMs,
  durationMs,
}: {
  stage: PipelineStage;
  startMs: number | null;
  durationMs: number;
}) {
  const { left, width, tone, label } = barGeometry(stage, startMs, durationMs);

  return (
    <div className="relative h-[18px] my-1 grid grid-cols-[64px_1fr] items-center gap-2.5">
      <div className="font-mono text-[10.5px] text-text-muted tracking-wider uppercase text-right font-semibold">
        {stage.label}
      </div>
      <div className="relative h-[18px] bg-white/[0.02] rounded">
        {width > 0 && (
          <div
            className="absolute top-[2px] bottom-[2px] rounded-[3px] flex items-center px-1.5 overflow-hidden font-mono text-[10px] font-semibold"
            style={{
              left: `${left}%`,
              width: `${Math.max(width, 0.6)}%`,
              background: tone.bg,
              color: tone.fg,
            }}
          >
            <span className="truncate">{label}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function barGeometry(
  stage: PipelineStage,
  startMs: number | null,
  durationMs: number,
): {
  left: number;
  width: number;
  tone: { bg: string; fg: string };
  label: string;
} {
  const tone = barTone(stage.status);
  if (!startMs || durationMs <= 0) {
    return { left: 0, width: 0, tone, label: "" };
  }
  const sStart = stage.started_at
    ? new Date(stage.started_at).getTime()
    : null;
  const sEnd = stage.completed_at
    ? new Date(stage.completed_at).getTime()
    : stage.status === "running"
      ? Date.now()
      : null;
  if (sStart == null || sEnd == null) {
    return { left: 0, width: 0, tone, label: "" };
  }
  const left = ((sStart - startMs) / durationMs) * 100;
  const width = ((sEnd - sStart) / durationMs) * 100;
  return {
    left: Math.max(0, left),
    width: Math.max(0, Math.min(100 - Math.max(0, left), width)),
    tone,
    label: shortSummary(stage),
  };
}

function barTone(status: string): { bg: string; fg: string } {
  if (status === "running")
    return {
      bg: "linear-gradient(90deg, var(--color-brand), var(--color-brand-strong))",
      fg: "#1a0e05",
    };
  if (status === "failed")
    return {
      bg: "linear-gradient(90deg, color-mix(in srgb, var(--color-status-failed) 85%, transparent), color-mix(in srgb, var(--color-status-failed) 55%, transparent))",
      fg: "#ffffff",
    };
  if (status === "awaiting")
    return {
      bg: "linear-gradient(90deg, color-mix(in srgb, var(--color-status-awaiting) 85%, transparent), color-mix(in srgb, var(--color-status-awaiting) 55%, transparent))",
      fg: "#1a0e05",
    };
  if (status === "done")
    return {
      bg: "linear-gradient(90deg, color-mix(in srgb, var(--color-status-done) 85%, transparent), color-mix(in srgb, var(--color-status-done) 55%, transparent))",
      fg: "#06140b",
    };
  return {
    bg: "color-mix(in srgb, var(--color-text-muted) 35%, transparent)",
    fg: "var(--color-text-secondary)",
  };
}

function shortSummary(stage: PipelineStage): string {
  // Use the part after the first " · " for compactness; falls back to the
  // full summary when there's no separator.
  const idx = stage.summary.indexOf(" · ");
  return idx >= 0
    ? stage.summary.slice(idx + 3)
    : stage.summary || stage.label;
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return s ? `${m}m ${String(s).padStart(2, "0")}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function formatNum(n: number): string {
  if (n === 0) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
