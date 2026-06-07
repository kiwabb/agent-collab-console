"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Clock,
  BarChart3,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getCodexCostStats,
  getCodexTasks,
  getIssueActivity,
  getIssuePipelineStages,
  type ActivityEvent,
  type CodexCostStats,
  type IssueChecklist,
  type PipelineStagesResponse,
  type PipelineStage,
} from "@/lib/api";
import type { CodexIssue, CodexTask } from "@/lib/types";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";
import { SimilarIssuesCard } from "./SimilarIssuesCard";
import { BudgetMeter } from "./BudgetMeter";
import { useIssueBudget } from "./useIssueBudget";

interface Props {
  issueId: string;
  checklist: IssueChecklist | null;
  reloadKey?: string | number;
  /** Optional full issue — used to drive budget-meter active-state polling. */
  issue?: CodexIssue | null;
}

/**
 * Right-side stack on the Issue Detail page — three stacked cards:
 *   - 验收清单 (acceptance checklist)
 *   - 活动 (activity timeline distilled from tasks/pipeline stages)
 *   - 消耗 (token/cost/duration telemetry + budget meter)
 */
export function IssueSideStack({ issueId, checklist, reloadKey, issue }: Props) {
  const { t } = useI18n();
  const [cost, setCost] = useState<CodexCostStats | null>(null);
  const [pipeline, setPipeline] = useState<PipelineStagesResponse | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  // tasks is now derived from pipeline.stages (one task per role) — no
  // separate fetch. Side-stack only needs a stage-level count.
  const tasks: CodexTask[] = [];

  // Budget meter — live WS events + mount fetch + active-state poll.
  // `isActive` drives the 30s poll. Default to **false** when `issue` is
  // missing: the hook should never poll blindly just because the caller
  // forgot to pass the issue. The mount fetch + WS path still work, so the
  // meter is at worst "stale until next event" — a safer degradation than
  // an unjustified 30s tick stream.
  const isActive = issue
    ? !["done", "completed", "cancelled", "abandoned", "closed"].includes(
        (issue.status ?? "").toLowerCase(),
      )
    : false;
  const { budget, loading: budgetLoading, refresh: refreshBudget } = useIssueBudget(
    issueId,
    isActive,
  );

  const refresh = useCallback(async () => {
    // Skip per-task list fetch — the side-stack only needs a stage-level
    // count and pipeline.stages.length is good enough. Saves one of the
    // ~10 /codex/tasks requests the page used to fire on load.
    const [c, p, a] = await Promise.all([
      getCodexCostStats({ issueId }).catch(() => null),
      getIssuePipelineStages(issueId).catch(() => null),
      getIssueActivity(issueId).catch(() => null),
    ]);
    setCost(c);
    setPipeline(p);
    setActivity(a?.events ?? []);
  }, [issueId]);

  useEffect(() => {
    void refresh();
    void refreshBudget();
  }, [refresh, refreshBudget, reloadKey]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn(
        "task_status",
        "task_created",
        "workflow_node_updated",
        "issue_updated",
      ),
    ),
    onEvent: () => {
      void refresh();
      void refreshBudget();
    },
    throttleMs: 600,
  });

  return (
    <aside data-density="insight-rail" className="flex flex-col gap-3 sticky top-4">
      <AcceptanceCard checklist={checklist} t={t} />
      <TelemetryCard
        cost={cost}
        pipeline={pipeline}
        taskCount={
          pipeline?.stages.filter((s) => s.task_id != null).length ?? 0
        }
        budget={budget}
        budgetLoading={budgetLoading}
        t={t}
      />
      <SimilarIssuesCard issueId={issueId} />
    </aside>
  );
}


type TFn = (key: string, params?: Record<string, string>) => string;

function Card({
  title,
  sub,
  icon: Icon,
  iconClass,
  children,
}: {
  title: string;
  sub?: string;
  icon: LucideIcon;
  iconClass?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="enterprise-panel border-border-subtle/60 bg-surface/90 rounded-lg overflow-hidden hover:border-border-strong/45 transition-colors">
      <div className="px-4 py-3 flex items-center gap-2.5 border-b border-border-subtle/60 bg-surface-input/30">
        <Icon size={15} className={cn("text-brand shrink-0", iconClass)} />
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {title}
        </span>
        {sub && (
          <span className="ml-auto font-mono text-[9px] text-text-muted uppercase tracking-wider font-black bg-surface-input px-2.5 py-0.5 rounded border border-border-subtle/40">
            {sub}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function AcceptanceCard({
  checklist,
  t,
}: {
  checklist: IssueChecklist | null;
  t: TFn;
}) {
  const criteria = checklist?.criteria ?? [];
  const total = criteria.length;
  const covered = criteria.filter((c) => c.covered).length;
  const pct = total > 0 ? Math.round((covered / total) * 100) : 0;

  return (
    <Card
      title={t("issue.side.acceptance")}
      sub={t("issue.side.acceptanceBy")}
      icon={CheckCircle2}
      iconClass="text-status-done"
    >
      <div className="px-4 py-3 flex items-center gap-3 bg-surface-input/30 m-3 rounded-lg border border-border-subtle/50">
        <span className="font-mono text-[22px] font-black tracking-tight leading-none text-foreground tabular-nums">
          {covered}
          <em className="not-italic text-text-muted font-normal text-sm">
            /{total}
          </em>
        </span>
        <div className="flex-1 h-2 bg-surface-input rounded-full overflow-hidden relative">
          <span
            className="block h-full rounded-full"
            style={{
              width: `${pct}%`,
              background:
                "linear-gradient(90deg, #34d977, var(--color-status-done))",
              boxShadow:
                "0 0 12px -2px color-mix(in srgb, var(--color-status-done) 60%, transparent)",
            }}
          />
        </div>
        <span className="font-mono text-[11px] font-bold text-status-done tabular-nums bg-status-done/10 px-1.5 py-0.5 rounded border border-status-done/20">
          {pct}%
        </span>
      </div>
      {total === 0 ? (
        <div className="px-5 pb-5 text-[12px] text-text-muted">
          {t("issue.side.acceptanceEmpty")}
        </div>
      ) : (
        <ul className="px-2 pb-3.5 flex flex-col gap-0.5">
          {criteria.map((c, i) => (
            <li
              key={i}
              className="flex items-start gap-2.5 px-3 py-2.5 rounded-md hover:bg-surface-hover/50 cursor-pointer transition-colors"
            >
              <span
                className={cn(
                  "shrink-0 size-[18px] rounded-full flex items-center justify-center mt-px transition-all duration-200",
                  c.covered
                    ? "bg-status-done/12 text-status-done border border-status-done/20"
                    : "bg-surface-input text-text-muted border border-border-subtle/40",
                )}
                style={
                  c.covered
                    ? { backgroundColor: "var(--color-done-bg)" }
                    : undefined
                }
              >
                {c.covered ? (
                  <CheckCircle2 size={11} strokeWidth={3} />
                ) : (
                  <Circle size={11} strokeWidth={2.5} />
                )}
              </span>
              <div className="text-[13px] leading-snug text-foreground">
                {c.text}
                {c.source && (
                  <span className="block font-mono text-[10px] text-text-faint mt-1 uppercase tracking-wider font-extrabold">
                    verified by {c.source}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ActivityCard({
  tasks,
  pipeline,
  activity,
  t,
}: {
  tasks: CodexTask[];
  pipeline: PipelineStagesResponse | null;
  activity: ActivityEvent[];
  t: TFn;
}) {
  // Prefer the backend's persistent activity stream when present; fall
  // back to deriving events from tasks + pipeline so the card stays
  // populated even on issues that predate the activity endpoint.
  const events = useMemo(
    () =>
      activity.length > 0
        ? activity.map(mapBackendEvent)
        : buildEvents(tasks, pipeline, t),
    [activity, tasks, pipeline, t],
  );
  return (
    <Card
      title={t("issue.side.activity")}
      sub={t("issue.side.activityEvents", { n: String(events.length) })}
      icon={Clock}
    >
      {events.length === 0 ? (
        <div className="px-5 py-5 text-[12px] text-text-muted">
          {t("issue.side.activityEmpty")}
        </div>
      ) : (
        <div className="relative px-5 pb-5 pt-1">
          <span
            aria-hidden
            className="absolute left-[29px] top-3.5 bottom-3.5 w-px"
            style={{
              background:
                "linear-gradient(180deg, transparent 0%, var(--color-border-muted) 8%, var(--color-border-muted) 92%, transparent 100%)",
            }}
          />
          {events.map((evt, i) => (
            <div
              key={i}
              className="relative grid grid-cols-[36px_1fr_auto] items-start gap-2.5 py-1.5"
            >
              <span
                className="relative z-[1] size-[18px] rounded-full border-2 justify-self-center mt-0.5"
                style={{
                  background: evt.dot,
                  borderColor: "var(--color-surface)",
                  boxShadow: `0 0 0 3px ${evt.ring}`,
                }}
              />
              <div className="min-w-0">
                <div
                  className="font-mono text-[10px] uppercase tracking-[0.08em] font-black mb-0.5"
                  style={{ color: evt.actorColor }}
                >
                  {evt.actor}
                </div>
                <div className="text-[12.5px] leading-snug text-foreground">
                  {evt.text}
                </div>
                {evt.aux && (
                  <div className="font-mono text-[10.5px] text-text-faint mt-0.5">
                    {evt.aux}
                  </div>
                )}
              </div>
              <span className="font-mono text-[11px] text-text-faint whitespace-nowrap mt-0.5">
                {evt.time}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function TelemetryCard({
  cost,
  pipeline,
  taskCount,
  budget,
  budgetLoading,
  t,
}: {
  cost: CodexCostStats | null;
  pipeline: PipelineStagesResponse | null;
  taskCount: number;
  budget: import("@/lib/types").IssueBudgetStatus | null;
  budgetLoading: boolean;
  t: TFn;
}) {
  const totalTokens =
    cost != null ? cost.input_tokens + cost.output_tokens : null;
  const totalDuration = pipeline?.total_duration_seconds ?? null;
  return (
    <Card
      title={t("issue.side.telemetry")}
      sub={t("issue.side.telemetrySub")}
      icon={BarChart3}
    >
      <div className="grid grid-cols-2 gap-3 p-3.5">
        <TeleCell label={t("issue.side.tokens")}>
          {totalTokens != null ? (
            <>
              {formatNum(totalTokens)}
              <em className="not-italic font-mono text-[11px] text-text-muted ml-1.5 font-normal">
                {t("issue.side.tokensSub")}
              </em>
            </>
          ) : (
            "—"
          )}
        </TeleCell>
        <TeleCell label={t("issue.side.cost")}>
          {cost ? `$${cost.est_cost_usd.toFixed(3)}` : "—"}
        </TeleCell>
        <TeleCell label={t("issue.side.duration")}>
          {totalDuration != null ? fmtDuration(totalDuration) : "—"}
        </TeleCell>
        <TeleCell label={t("issue.side.runs")}>
          {taskCount > 0 ? (
            <>
              {taskCount}{" "}
              <em className="not-italic font-mono text-[11px] text-text-muted ml-1.5 font-normal">
                {t("issue.side.runsSub")}
              </em>
            </>
          ) : (
            "—"
          )}
        </TeleCell>
      </div>
      <div className="border-t border-border-subtle/40">
        <BudgetMeter status={budget} loading={budgetLoading} />
      </div>
    </Card>
  );
}

function TeleCell({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="p-3.5 rounded-lg bg-surface-input/35 border border-border-subtle/50 transition-colors hover:bg-surface-input/50">
      <div className="font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
        {label}
      </div>
      <div className="text-[18px] font-black text-foreground tracking-tight mt-2 font-mono">
        {children}
      </div>
    </div>
  );
}

interface ActivityEvt {
  actor: string;
  actorColor: string;
  text: string;
  aux?: string;
  time: string;
  dot: string;
  ring: string;
}

function mapBackendEvent(e: ActivityEvent): ActivityEvt {
  // Color/tone selection based on the event type. Backend types include:
  //  issue_created, task_started, task_done, task_failed, audit_*
  const isDone = e.type === "task_done";
  const isFailed = e.type === "task_failed";
  const isAudit = e.type.startsWith("audit_");
  const tone = isDone
    ? {
        dot: "var(--color-status-done)",
        ring: "var(--color-done-bg)",
        actorColor: "var(--color-status-done)",
      }
    : isFailed
      ? {
          dot: "var(--color-status-failed)",
          ring: "var(--color-failed-bg)",
          actorColor: "var(--color-status-failed)",
        }
      : isAudit
        ? {
            dot: "var(--color-status-tool)",
            ring: "var(--color-tool-bg)",
            actorColor: "var(--color-status-tool)",
          }
        : e.type === "task_started"
          ? {
              dot: "var(--color-brand)",
              ring: "var(--color-brand-bg)",
              actorColor: "var(--color-brand)",
            }
          : {
              dot: "var(--color-status-info)",
              ring: "var(--color-info-bg)",
              actorColor: "var(--color-status-info)",
            };
  return {
    actor: e.actor,
    actorColor: tone.actorColor,
    text: e.text,
    aux: e.aux ?? undefined,
    time: fmtTimeOnly(e.timestamp),
    dot: tone.dot,
    ring: tone.ring,
  };
}

function buildEvents(
  tasks: CodexTask[],
  pipeline: PipelineStagesResponse | null,
  t: TFn,
): ActivityEvt[] {
  const out: ActivityEvt[] = [];

  // Issue creation event from the earliest task's created_at, if any.
  if (tasks.length) {
    const earliest = [...tasks].sort((a, b) =>
      (a.created_at ?? "").localeCompare(b.created_at ?? ""),
    )[0];
    if (earliest?.created_at) {
      out.push({
        actor: t("issue.side.activityRoleSystem"),
        actorColor: "var(--color-status-info)",
        text: t("issue.side.activityCreated"),
        time: fmtTimeOnly(earliest.created_at),
        dot: "var(--color-status-info)",
        ring: "var(--color-info-bg)",
      });
    }
  }

  const roleLabel: Record<string, string> = {
    product_manager: t("issue.side.activityRoleAgent", { label: "PM" }),
    architect: t("issue.side.activityRoleAgent", { label: "Architect" }),
    engineer: t("issue.side.activityRoleAgent", { label: "Engineer" }),
    qa: t("issue.side.activityRoleAgent", { label: "QA" }),
  };

  // One event per role using the pipeline stage if available, else fall back
  // to a task lookup. Stages already encode summary + status + timestamps.
  if (pipeline) {
    for (const s of pipeline.stages) {
      if (s.status === "pending") continue;
      out.push(stageToEvt(s, roleLabel, t));
    }
  } else {
    const seen = new Set<string>();
    for (const t of tasks) {
      if (!t.role || seen.has(t.role)) continue;
      seen.add(t.role);
      const status = t.status ?? "pending";
      if (status === "pending") continue;
      out.push({
        actor: roleLabel[t.role] ?? t.role,
        actorColor:
          status === "done"
            ? "var(--color-status-done)"
            : status === "failed"
              ? "var(--color-status-failed)"
              : "var(--color-brand)",
        text: t.title || "(no title)",
        time: fmtTimeOnly(t.updated_at ?? t.created_at ?? null),
        dot:
          status === "done"
            ? "var(--color-status-done)"
            : status === "failed"
              ? "var(--color-status-failed)"
              : "var(--color-brand)",
        ring:
          status === "done"
            ? "var(--color-done-bg)"
            : status === "failed"
              ? "var(--color-failed-bg)"
              : "var(--color-brand-bg)",
      });
    }
  }

  // Pipeline completion event if everything is done.
  if (
    pipeline &&
    pipeline.completed_at &&
    pipeline.stages.length > 0 &&
    pipeline.stages.every((s) => s.status === "done")
  ) {
    out.push({
      actor: t("issue.side.activityPipelineLabel"),
      actorColor: "var(--color-status-done)",
      text: t("issue.side.activityPipelineDone"),
      time: fmtTimeOnly(pipeline.completed_at),
      dot: "var(--color-status-done)",
      ring: "var(--color-done-bg)",
    });
  }

  return out;
}

function stageToEvt(
  s: PipelineStage,
  roleLabel: Record<string, string>,
  t: TFn,
): ActivityEvt {
  const actor = roleLabel[s.role] ?? s.label;
  if (s.status === "done") {
    return {
      actor: t("issue.side.activityRolePassed", { label: s.label }),
      actorColor: "var(--color-status-done)",
      text: s.summary || t("issue.trace.completedAt"),
      aux: s.foot || undefined,
      time: fmtTimeOnly(s.completed_at ?? s.started_at),
      dot: "var(--color-status-done)",
      ring: "var(--color-done-bg)",
    };
  }
  if (s.status === "failed") {
    return {
      actor: t("issue.side.activityRoleFailed", { label: s.label }),
      actorColor: "var(--color-status-failed)",
      text: s.summary || t("issue.trace.stageFailed"),
      time: fmtTimeOnly(s.completed_at ?? s.started_at),
      dot: "var(--color-status-failed)",
      ring: "var(--color-failed-bg)",
    };
  }
  if (s.status === "running") {
    return {
      actor,
      actorColor: "var(--color-brand)",
      text: s.summary || t("issue.trace.runningNow"),
      time: fmtTimeOnly(s.started_at),
      dot: "var(--color-brand)",
      ring: "var(--color-brand-bg)",
    };
  }
  if (s.status === "awaiting") {
    return {
      actor: t("issue.side.activityRoleAwaiting", { label: s.label }),
      actorColor: "var(--color-status-awaiting)",
      text: s.summary || t("issue.trace.stageAwaiting"),
      time: fmtTimeOnly(s.started_at),
      dot: "var(--color-status-awaiting)",
      ring: "var(--color-warning-bg)",
    };
  }
  return {
    actor,
    actorColor: "var(--color-text-muted)",
    text: s.summary || t("issue.trace.stagePending"),
    time: fmtTimeOnly(s.started_at),
    dot: "var(--color-text-muted)",
    ring: "transparent",
  };
}

function fmtTimeOnly(iso: string | null | undefined): string {
  if (!iso) return "—";
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

function formatNum(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
