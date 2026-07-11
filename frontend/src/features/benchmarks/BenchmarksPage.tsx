"use client";

import { useCallback, useEffect, useState } from "react";
import { useI18n } from "@/providers/I18nProvider";
import type {
  BenchmarkDiff,
  BenchmarkJob,
  BenchmarkRun,
  CalibrationReport,
  Project,
  Workspace,
} from "@/lib/types";
import {
  getBenchmarkJob,
  triggerBenchmarkRun,
  type TriggerBenchmarkResponse,
} from "@/lib/api/benchmarks";
import { listProjects } from "@/lib/api/projects";
import { getWorkspaces } from "@/lib/api/workspaces";
import { cn } from "@/lib/utils";
import {
  fmtPassAt1,
  fmtTimestamp,
  fmtUsd,
  benchmarkTargetError,
  buildBenchmarkTriggerBody,
  pickLogTicksRounded,
  projectPoints,
  summarizeDiff,
  type DiffStatus,
  type FrontierPoint,
  type ProjectedPoint,
  type ChartBox,
} from "./helpers";

const CHART_BOX: ChartBox = {
  width: 480,
  height: 280,
  padLeft: 44,
  padRight: 12,
  padTop: 12,
  padBottom: 32,
};

type BenchmarkTargetLoadErrorKey =
  | "benchmark.trigger.target.noProjects"
  | "benchmark.trigger.target.projectsLoadFailed"
  | "benchmark.trigger.target.noWorkspaces"
  | "benchmark.trigger.target.workspacesLoadFailed";

const BENCHMARK_TARGET_ERROR_KEYS = {
  project_required: "benchmark.trigger.target.projectRequired",
  workspace_required: "benchmark.trigger.target.workspaceRequired",
} as const;

// ---------------------------------------------------------------------------
// Trigger form
// ---------------------------------------------------------------------------

interface TriggerFormProps {
  onStarted: (job: TriggerBenchmarkResponse) => void;
  onError: (message: string) => void;
  onViewJob: (jobId: string) => void;
}

export function TriggerForm({ onStarted, onError, onViewJob }: TriggerFormProps) {
  const { t } = useI18n();
  const [label, setLabel] = useState("");
  const [epochs, setEpochs] = useState(3);
  const [dryRun, setDryRun] = useState(true);
  const [maxBudget, setMaxBudget] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [lastJob, setLastJob] = useState<TriggerBenchmarkResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projectId, setProjectId] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [workspacesLoading, setWorkspacesLoading] = useState(false);
  const [targetLoadError, setTargetLoadError] = useState<BenchmarkTargetLoadErrorKey | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setProjectsLoading(true);
      try {
        const items = await listProjects();
        if (cancelled) return;
        setProjects(items);
        setProjectId((current) => current || items[0]?.id || "");
        if (items.length === 0) {
          setTargetLoadError("benchmark.trigger.target.noProjects");
        }
      } catch (error) {
        console.error("Failed to load benchmark projects", error);
        if (!cancelled) setTargetLoadError("benchmark.trigger.target.projectsLoadFailed");
      } finally {
        if (!cancelled) setProjectsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    const load = async () => {
      setWorkspacesLoading(true);
      setTargetLoadError(null);
      try {
        const items = await getWorkspaces(projectId);
        if (cancelled) return;
        setWorkspaces(items);
        setWorkspaceId((current) =>
          items.some((workspace) => workspace.id === current) ? current : items[0]?.id || "",
        );
        if (items.length === 0) {
          setTargetLoadError("benchmark.trigger.target.noWorkspaces");
        }
      } catch (error) {
        console.error("Failed to load benchmark workspaces", error);
        if (!cancelled) {
          setTargetLoadError("benchmark.trigger.target.workspacesLoadFailed");
        }
      } finally {
        if (!cancelled) setWorkspacesLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const selectionError = benchmarkTargetError(dryRun, projectId, workspaceId);
      if (selectionError) {
        onError(t(BENCHMARK_TARGET_ERROR_KEYS[selectionError]));
        return;
      }
      setSubmitting(true);
      onError("");
      try {
        let maxBudgetUsd: number | undefined;
        if (maxBudget.trim()) {
          const parsed = Number.parseFloat(maxBudget);
          if (Number.isFinite(parsed) && parsed > 0) maxBudgetUsd = parsed;
        }
        const body = buildBenchmarkTriggerBody({
          label,
          epochs,
          dryRun,
          projectId,
          workspaceId,
          maxBudgetUsd,
        });
        const res = await triggerBenchmarkRun(body);
        setLastJob(res);
        onStarted(res);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        onError(message);
      } finally {
        setSubmitting(false);
      }
    },
    [label, epochs, dryRun, maxBudget, onError, onStarted, projectId, t, workspaceId],
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden"
    >
      <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30">
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {t("benchmark.trigger.title")}
        </span>
      </div>
      <div className="p-5 grid grid-cols-2 gap-4">
        <label className="flex flex-col gap-1.5 col-span-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
            {t("benchmark.trigger.label")}
          </span>
          <input
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t("benchmark.trigger.label.placeholder")}
            className="bg-surface-input/50 border border-border-subtle/40 rounded-md px-3 py-2 text-[13px] text-foreground placeholder:text-text-faint focus:outline-none focus:border-brand/60"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
            {t("benchmark.trigger.epochs")}
          </span>
          <input
            type="number"
            min={1}
            value={epochs}
            onChange={(e) => setEpochs(Math.max(1, Number.parseInt(e.target.value || "1", 10)))}
            className="bg-surface-input/50 border border-border-subtle/40 rounded-md px-3 py-2 text-[13px] text-foreground font-mono focus:outline-none focus:border-brand/60"
          />
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
            {t("benchmark.trigger.maxBudget")}
          </span>
          <input
            type="number"
            min={0}
            step="0.5"
            value={maxBudget}
            onChange={(e) => setMaxBudget(e.target.value)}
            placeholder="—"
            className="bg-surface-input/50 border border-border-subtle/40 rounded-md px-3 py-2 text-[13px] text-foreground font-mono placeholder:text-text-faint focus:outline-none focus:border-brand/60"
          />
        </label>
        <label className="flex items-center gap-2.5 col-span-2 cursor-pointer">
          <input
            type="checkbox"
            checked={dryRun}
            onChange={(e) => setDryRun(e.target.checked)}
            className="size-4 rounded border-border-subtle/40 accent-brand"
          />
          <span className="text-[12px] text-foreground">{t("benchmark.trigger.dryRun")}</span>
        </label>
        {!dryRun && (
          <fieldset className="col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-4 border-t border-border-subtle/40 pt-4">
            <legend className="font-mono text-[9px] uppercase font-extrabold text-text-muted pr-2">
              {t("benchmark.trigger.target.legend")}
            </legend>
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[9px] uppercase font-extrabold text-text-muted">
                {t("benchmark.trigger.target.project")}
              </span>
              <select
                value={projectId}
                onChange={(event) => {
                  setProjectId(event.target.value);
                  setWorkspaceId("");
                  setWorkspaces([]);
                }}
                disabled={projectsLoading || projects.length === 0}
                required
                className="min-h-11 bg-surface-input/50 border border-border-subtle/40 rounded-md px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-brand/60 disabled:opacity-50"
              >
                <option value="">
                  {projectsLoading
                    ? t("benchmark.trigger.target.loadingProjects")
                    : t("benchmark.trigger.target.selectProject")}
                </option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[9px] uppercase font-extrabold text-text-muted">
                {t("benchmark.trigger.target.workspace")}
              </span>
              <select
                value={workspaceId}
                onChange={(event) => setWorkspaceId(event.target.value)}
                disabled={!projectId || workspacesLoading || workspaces.length === 0}
                required
                className="min-h-11 bg-surface-input/50 border border-border-subtle/40 rounded-md px-3 py-2 text-[13px] text-foreground focus:outline-none focus:border-brand/60 disabled:opacity-50"
              >
                <option value="">
                  {workspacesLoading
                    ? t("benchmark.trigger.target.loadingWorkspaces")
                    : t("benchmark.trigger.target.selectWorkspace")}
                </option>
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.title}
                  </option>
                ))}
              </select>
            </label>
            {targetLoadError && (
              <p role="alert" className="sm:col-span-2 text-[11px] text-status-failed">
                {t(targetLoadError)}
              </p>
            )}
          </fieldset>
        )}
      </div>
      <div className="px-5 py-3 border-t border-border-subtle/40 flex items-center gap-3">
        <button
          type="submit"
          disabled={
            submitting ||
            (!dryRun && (projectsLoading || workspacesLoading || !projectId || !workspaceId))
          }
          className="px-4 py-2 rounded-md bg-brand text-white text-[12.5px] font-bold tracking-wide hover:opacity-90 disabled:opacity-50 transition"
        >
          {submitting ? t("benchmark.trigger.submitting") : t("benchmark.trigger.submit")}
        </button>
        {lastJob && (
          <button
            type="button"
            onClick={() => onViewJob(lastJob.job_id)}
            className="text-[11px] font-mono text-brand hover:underline"
          >
            {t("benchmark.trigger.viewJob")} · {lastJob.job_id}
          </button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Job poller
// ---------------------------------------------------------------------------

export function useBenchmarkJob(jobId: string | null): {
  job: BenchmarkJob | null;
  resultRef: string | null;
} {
  const [job, setJob] = useState<BenchmarkJob | null>(null);
  useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      const next = await getBenchmarkJob(jobId);
      if (cancelled) return;
      setJob(next);
      if (next && (next.status === "pending" || next.status === "running")) {
        timer = setTimeout(tick, 1500);
      }
    };
    void tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);
  return { job, resultRef: job?.result_ref ?? null };
}

// ---------------------------------------------------------------------------
// Leaderboard
// ---------------------------------------------------------------------------

interface LeaderboardProps {
  runs: BenchmarkRun[];
  baseline: BenchmarkRun | null;
  onRefresh: () => void;
  onSetBaseline: (runId: string) => void;
  onViewDiff: (runId: string) => void;
}

export function Leaderboard({
  runs,
  baseline,
  onRefresh,
  onSetBaseline,
  onViewDiff,
}: LeaderboardProps) {
  const { t } = useI18n();
  if (runs.length === 0) {
    return (
      <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
        <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30 flex items-center gap-2">
          <span className="text-[13px] font-bold tracking-wide text-foreground">
            {t("benchmark.leaderboard.title")}
          </span>
        </div>
        <div className="px-5 py-8 text-center text-[12px] text-text-muted">
          {t("benchmark.leaderboard.empty")}
        </div>
      </div>
    );
  }
  return (
    <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
      <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30 flex items-center gap-2">
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {t("benchmark.leaderboard.title")}
        </span>
        <span className="ml-auto font-mono text-[10px] text-text-muted">({runs.length})</span>
        <button
          type="button"
          onClick={onRefresh}
          className="text-[11px] font-mono text-text-muted hover:text-foreground"
        >
          ↻
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border-subtle/40 bg-slate-900/20 text-text-muted">
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.leaderboard.col.label")}
              </th>
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.leaderboard.col.created")}
              </th>
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.leaderboard.col.status")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.leaderboard.col.passAt1")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.leaderboard.col.costPer")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.leaderboard.col.epochs")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {" "}
              </th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const isBaseline = baseline?.id === r.id;
              return (
                <tr
                  key={r.id}
                  className={cn(
                    "border-b border-border-subtle/30 hover:bg-surface-hover/40",
                    isBaseline && "bg-status-done/5",
                  )}
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[12px] text-foreground">
                        {r.label || r.id}
                      </span>
                      {isBaseline && (
                        <span className="font-mono text-[9px] uppercase tracking-wider font-extrabold text-status-done bg-status-done/10 px-1.5 py-0.5 rounded">
                          {t("benchmark.leaderboard.baseline")}
                        </span>
                      )}
                      {r.is_synthetic && (
                        <span className="font-mono text-[9px] uppercase font-extrabold text-status-awaiting bg-status-awaiting/10 px-1.5 py-0.5 rounded">
                          {t("benchmark.leaderboard.synthetic")}
                        </span>
                      )}
                    </div>
                    <div className="font-mono text-[9px] text-text-faint">{r.id}</div>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-[11px] text-text-muted">
                    {fmtTimestamp(r.created_at)}
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] tabular-nums">
                    {fmtPassAt1(r.aggregate_pass_at_1, r.aggregate_pass_at_1_stderr)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[12px] tabular-nums">
                    {fmtUsd(r.cost_per_issue_usd)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-[11px] text-text-muted">
                    {r.n_epochs ?? "—"}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="flex justify-end gap-1.5">
                      {!isBaseline && !r.is_synthetic && r.status === "completed" && (
                        <button
                          type="button"
                          onClick={() => onSetBaseline(r.id)}
                          className="font-mono text-[10px] text-text-muted hover:text-foreground"
                        >
                          {t("benchmark.leaderboard.setBaseline")}
                        </button>
                      )}
                      {!r.is_synthetic && r.status === "completed" && (
                        <button
                          type="button"
                          onClick={() => onViewDiff(r.id)}
                          className="font-mono text-[10px] text-brand hover:underline"
                        >
                          {t("benchmark.leaderboard.viewDiff")}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: BenchmarkRun["status"] }) {
  const { t } = useI18n();
  const tone =
    status === "completed"
      ? "bg-status-done/10 text-status-done border-status-done/20"
      : status === "failed"
        ? "bg-status-failed/10 text-status-failed border-status-failed/20"
        : "bg-status-info/10 text-status-info border-status-info/20";
  return (
    <span
      className={cn(
        "inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider border",
        tone,
      )}
    >
      {t(`benchmark.status.${status}` as Parameters<typeof t>[0])}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Score × cost frontier (hand-rolled SVG)
// ---------------------------------------------------------------------------

interface ScoreCostFrontierProps {
  runs: BenchmarkRun[];
  baseline: BenchmarkRun | null;
  onPickRun: (runId: string) => void;
}

export function ScoreCostFrontier({ runs, baseline, onPickRun }: ScoreCostFrontierProps) {
  const { t } = useI18n();
  const completed = runs.filter(
    (r) =>
      r.status === "completed" &&
      !r.is_synthetic &&
      typeof r.cost_per_issue_usd === "number" &&
      typeof r.aggregate_pass_at_1 === "number",
  );
  if (completed.length < 2) {
    return (
      <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
        <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30">
          <span className="text-[13px] font-bold tracking-wide text-foreground">
            {t("benchmark.frontier.title")}
          </span>
        </div>
        <div className="px-5 py-8 text-center text-[12px] text-text-muted">
          {t("benchmark.frontier.empty")}
        </div>
      </div>
    );
  }

  const points: FrontierPoint[] = completed.flatMap((r) => {
    if (typeof r.cost_per_issue_usd !== "number" || typeof r.aggregate_pass_at_1 !== "number") {
      return [];
    }
    return [
      {
        runId: r.id,
        label: r.label || r.id,
        isBaseline: baseline?.id === r.id,
        costPerIssueUsd: r.cost_per_issue_usd,
        passAt1: r.aggregate_pass_at_1,
      },
    ];
  });
  const { projected, axis } = projectPoints(points, CHART_BOX);
  const ticks = pickLogTicksRounded(axis.xMin, axis.xMax, 4);

  return (
    <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
      <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30">
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {t("benchmark.frontier.title")}
        </span>
      </div>
      <div className="p-4 flex justify-center">
        <svg
          width={CHART_BOX.width}
          height={CHART_BOX.height}
          className="font-mono text-[10px]"
          role="img"
          aria-label={t("benchmark.frontier.title")}
        >
          {/* axes */}
          <line
            x1={CHART_BOX.padLeft}
            y1={CHART_BOX.padTop}
            x2={CHART_BOX.padLeft}
            y2={CHART_BOX.height - CHART_BOX.padBottom}
            stroke="currentColor"
            className="text-border-subtle"
            strokeWidth={1}
          />
          <line
            x1={CHART_BOX.padLeft}
            y1={CHART_BOX.height - CHART_BOX.padBottom}
            x2={CHART_BOX.width - CHART_BOX.padRight}
            y2={CHART_BOX.height - CHART_BOX.padBottom}
            stroke="currentColor"
            className="text-border-subtle"
            strokeWidth={1}
          />
          {/* y-axis labels (0%, 50%, 100%) */}
          {[0, 0.25, 0.5, 0.75, 1].map((p) => {
            const y =
              CHART_BOX.padTop +
              (1 - p) * (CHART_BOX.height - CHART_BOX.padTop - CHART_BOX.padBottom);
            return (
              <g key={p}>
                <line
                  x1={CHART_BOX.padLeft - 3}
                  y1={y}
                  x2={CHART_BOX.padLeft}
                  y2={y}
                  stroke="currentColor"
                  className="text-border-subtle"
                />
                <text
                  x={CHART_BOX.padLeft - 6}
                  y={y + 3}
                  textAnchor="end"
                  className="fill-text-muted"
                >
                  {`${Math.round(p * 100)}%`}
                </text>
              </g>
            );
          })}
          {/* x-axis labels (log cost ticks) */}
          {ticks.map((t) => {
            const innerW = CHART_BOX.width - CHART_BOX.padLeft - CHART_BOX.padRight;
            const xMin = Math.log10(axis.xMin);
            const xMax = Math.log10(axis.xMax);
            const tPos = xMax - xMin < 0.01 ? 0.5 : (Math.log10(t) - xMin) / (xMax - xMin);
            const x = CHART_BOX.padLeft + tPos * innerW;
            return (
              <g key={t}>
                <line
                  x1={x}
                  y1={CHART_BOX.height - CHART_BOX.padBottom}
                  x2={x}
                  y2={CHART_BOX.height - CHART_BOX.padBottom + 3}
                  stroke="currentColor"
                  className="text-border-subtle"
                />
                <text
                  x={x}
                  y={CHART_BOX.height - CHART_BOX.padBottom + 14}
                  textAnchor="middle"
                  className="fill-text-muted"
                >
                  {fmtUsd(t)}
                </text>
              </g>
            );
          })}
          {/* axis titles */}
          <text
            x={CHART_BOX.width / 2}
            y={CHART_BOX.height - 4}
            textAnchor="middle"
            className="fill-text-muted text-[9px] uppercase tracking-wider"
          >
            {t("benchmark.frontier.xAxis")}
          </text>
          <text
            transform={`rotate(-90 10 ${CHART_BOX.height / 2})`}
            x={10}
            y={CHART_BOX.height / 2}
            textAnchor="middle"
            className="fill-text-muted text-[9px] uppercase tracking-wider"
          >
            {t("benchmark.frontier.yAxis")}
          </text>
          {/* points */}
          {projected.map((p) => (
            <FrontierDot
              key={p.runId}
              p={p}
              isBaseline={p.isBaseline}
              onClick={() => onPickRun(p.runId)}
            />
          ))}
        </svg>
      </div>
    </div>
  );
}

function FrontierDot({
  p,
  isBaseline,
  onClick,
}: {
  p: ProjectedPoint;
  isBaseline: boolean;
  onClick: () => void;
}) {
  const tone = isBaseline ? "fill-status-done" : "fill-brand";
  return (
    <g onClick={onClick} className="cursor-pointer">
      <circle cx={p.px} cy={p.py} r={p.r + 4} fill="transparent" />
      <circle cx={p.px} cy={p.py} r={p.r} className={tone} stroke="white" strokeWidth={1.5} />
      <title>{`${p.label} (${p.runId})`}</title>
    </g>
  );
}

// ---------------------------------------------------------------------------
// Run diff
// ---------------------------------------------------------------------------

interface RunDiffPanelProps {
  diff: BenchmarkDiff | null;
  loading: boolean;
}

export function RunDiffPanel({ diff, loading }: RunDiffPanelProps) {
  const { t } = useI18n();
  if (loading) {
    return (
      <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden p-5 text-center text-[12px] text-text-muted">
        {t("benchmark.empty")}
      </div>
    );
  }
  if (!diff) {
    return (
      <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden p-5 text-center text-[12px] text-text-muted">
        {t("benchmark.empty")}
      </div>
    );
  }
  if (diff.diff === null) {
    return (
      <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
        <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30">
          <span className="text-[13px] font-bold tracking-wide text-foreground">
            {t("benchmark.diff.title")}
          </span>
        </div>
        <div className="px-5 py-8 text-center text-[12px] text-text-muted">
          {diff.note?.includes("IS the baseline")
            ? t("benchmark.diff.candidateIsBaseline")
            : t("benchmark.diff.noBaseline")}
        </div>
      </div>
    );
  }

  const summary = summarizeDiff(diff.diff.per_fixture);
  const aggTone =
    diff.diff.aggregate_status === "regressed"
      ? "text-status-failed"
      : diff.diff.aggregate_status === "improved"
        ? "text-status-done"
        : "text-text-muted";

  return (
    <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
      <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30 flex items-center gap-3">
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {t("benchmark.diff.title")}
        </span>
        <span
          className={cn(
            "ml-auto font-mono text-[10px] uppercase tracking-wider font-extrabold px-2 py-0.5 rounded border",
            diff.diff.aggregate_status === "regressed"
              ? "text-status-failed bg-status-failed/10 border-status-failed/20"
              : diff.diff.aggregate_status === "improved"
                ? "text-status-done bg-status-done/10 border-status-done/20"
                : "text-text-muted bg-surface-input/50 border-border-subtle/40",
          )}
        >
          {t(
            `benchmark.diff.status${capitalize(diff.diff.aggregate_status)}` as Parameters<
              typeof t
            >[0],
          )}
        </span>
      </div>
      <div className="px-5 py-3 grid grid-cols-3 gap-3 text-[12px]">
        <SummaryStat
          label={t("benchmark.diff.aggregateLabel")}
          value={fmtPassAt1(
            diff.candidate.aggregate_pass_at_1,
            diff.candidate.aggregate_pass_at_1_stderr,
          )}
        />
        <SummaryStat
          label={t("benchmark.diff.aggregateDelta")}
          value={
            diff.diff.aggregate_delta >= 0
              ? `+${(diff.diff.aggregate_delta * 100).toFixed(1)}pp`
              : `${(diff.diff.aggregate_delta * 100).toFixed(1)}pp`
          }
          tone={aggTone}
        />
        <SummaryStat
          label={t("benchmark.diff.regressedCount", { n: String(summary.regressed) })}
          value={t("benchmark.diff.improvedCount", { n: String(summary.improved) })}
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border-subtle/40 bg-slate-900/20 text-text-muted">
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.diff.col.fixture")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.diff.col.candidate")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.diff.col.baseline")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.diff.col.delta")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.diff.col.status")}
              </th>
            </tr>
          </thead>
          <tbody>
            {diff.diff.per_fixture.map((f) => (
              <tr key={f.fixture_id} className="border-b border-border-subtle/30">
                <td className="px-3 py-2 font-mono text-[11px] text-foreground">{f.fixture_id}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {fmtPctShort(f.candidate_pass_at_1)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-text-muted">
                  {fmtPctShort(f.baseline_pass_at_1)}
                </td>
                <td
                  className={cn("px-3 py-2 text-right font-mono tabular-nums", toneFor(f.status))}
                >
                  {f.delta >= 0 ? "+" : ""}
                  {(f.delta * 100).toFixed(1)}pp
                </td>
                <td className="px-3 py-2 text-right">
                  <DiffStatusPill status={f.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  tone = "text-foreground",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="p-3 rounded-md bg-surface-input/30 border border-border-subtle/40">
      <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-text-muted">
        {label}
      </div>
      <div className={cn("text-[15px] font-mono font-black tabular-nums mt-1", tone)}>{value}</div>
    </div>
  );
}

function DiffStatusPill({ status }: { status: DiffStatus }) {
  const { t } = useI18n();
  const tone =
    status === "improved"
      ? "text-status-done bg-status-done/10 border-status-done/20"
      : status === "regressed"
        ? "text-status-failed bg-status-failed/10 border-status-failed/20"
        : "text-text-muted bg-surface-input/50 border-border-subtle/40";
  return (
    <span
      className={cn(
        "inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider border",
        tone,
      )}
    >
      {t(`benchmark.diff.status${capitalize(status)}` as Parameters<typeof t>[0])}
    </span>
  );
}

function toneFor(status: DiffStatus): string {
  if (status === "improved") return "text-status-done";
  if (status === "regressed") return "text-status-failed";
  return "text-text-muted";
}

function fmtPctShort(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// Calibration panel
// ---------------------------------------------------------------------------

interface CalibrationPanelProps {
  report: CalibrationReport | null;
}

export function CalibrationPanel({ report }: CalibrationPanelProps) {
  const { t } = useI18n();
  if (!report) {
    return (
      <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden p-5 text-center text-[12px] text-text-muted">
        {t("benchmark.empty")}
      </div>
    );
  }
  const tone = report.is_calibrated
    ? "text-status-done bg-status-done/10 border-status-done/20"
    : "text-status-awaiting bg-status-awaiting/10 border-status-awaiting/20";
  return (
    <div className="enterprise-panel border-border-subtle/40 bg-surface/75 backdrop-blur-xl rounded-[24px] overflow-hidden">
      <div className="px-5 py-4 border-b border-border-subtle/50 bg-slate-900/30 flex items-center gap-3">
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {t("benchmark.calibration.title")}
        </span>
        <span
          className={cn(
            "ml-auto font-mono text-[10px] uppercase tracking-wider font-extrabold px-2 py-0.5 rounded border",
            tone,
          )}
        >
          {report.is_calibrated
            ? t("benchmark.calibration.calibrated")
            : t("benchmark.calibration.uncalibrated")}
        </span>
      </div>
      <div className="px-5 py-3 grid grid-cols-3 gap-3 text-[12px]">
        <SummaryStat label={t("benchmark.calibration.pearson")} value={report.pearson.toFixed(3)} />
        <SummaryStat
          label={t("benchmark.calibration.spearman")}
          value={report.spearman.toFixed(3)}
        />
        <SummaryStat
          label={t("benchmark.calibration.weakest")}
          value={report.weakest_item ?? "—"}
        />
      </div>
      <div className="px-5 py-2 text-[11px] font-mono text-text-muted">
        {t("benchmark.calibration.floor", { floor: String(report.floor) })}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-border-subtle/40 bg-slate-900/20 text-text-muted">
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.calibration.col.id")}
              </th>
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.calibration.col.fixture")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.calibration.col.human")}
              </th>
              <th className="px-3 py-2 text-right font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.calibration.col.judge")}
              </th>
              <th className="px-3 py-2 text-left font-mono text-[10px] uppercase tracking-wider">
                {t("benchmark.calibration.col.note")}
              </th>
            </tr>
          </thead>
          <tbody>
            {report.items.map((it) => (
              <tr key={it.id} className="border-b border-border-subtle/30">
                <td className="px-3 py-2 font-mono text-[11px] text-foreground">{it.id}</td>
                <td className="px-3 py-2 font-mono text-[11px] text-text-muted">
                  {it.fixture_id ?? "—"}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {fmtPctShort(it.human_score)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums text-text-faint">
                  {it.judge_score == null ? "—" : fmtPctShort(it.judge_score)}
                </td>
                <td className="px-3 py-2 text-[11px] text-text-muted max-w-md truncate">
                  {it.note ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tabs (controlled by the parent page)
// ---------------------------------------------------------------------------

export type BenchmarkTab = "leaderboard" | "frontier" | "diff" | "calibration";
