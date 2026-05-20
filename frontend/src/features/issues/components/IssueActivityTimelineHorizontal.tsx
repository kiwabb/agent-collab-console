"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getIssueActivity,
  getIssuePipelineStages,
  type ActivityEvent,
  type PipelineStagesResponse,
} from "@/lib/api";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
  reloadKey?: string | number;
}

type Bucket = "agent" | "tool" | "system" | "done";

/**
 * Horizontal activity timeline rendered below the body grid.
 *
 *   ┌──card──┐               ┌──card──┐
 *   │ top    │               │ top    │
 *   └────────┘               └────────┘
 *      ●───────●───────●───────●───────●
 *           ┌──card──┐    ┌──card──┐
 *           │ bottom │    │ bottom │
 *           └────────┘    └────────┘
 *
 * Events are placed by their timestamp's percent position on the
 * pipeline window. Even/odd indices alternate above/below the axis so
 * cards don't collide.
 */
export function IssueActivityTimelineHorizontal({ issueId, reloadKey }: Props) {
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [pipeline, setPipeline] = useState<PipelineStagesResponse | null>(null);
  const [filter, setFilter] = useState<"all" | Bucket>("all");

  const refresh = useCallback(async () => {
    const [a, p] = await Promise.all([
      getIssueActivity(issueId, 30).catch(() => null),
      getIssuePipelineStages(issueId).catch(() => null),
    ]);
    setActivity(a?.events ?? []);
    setPipeline(p);
  }, [issueId]);

  useEffect(() => {
    void refresh();
  }, [refresh, reloadKey]);

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
    },
    throttleMs: 600,
  });

  const { startMs, endMs, durationMs } = useMemo(() => {
    const allTs: number[] = [];
    for (const e of activity) {
      const t = Date.parse(e.timestamp);
      if (!Number.isNaN(t)) allTs.push(t);
    }
    if (pipeline?.started_at)
      allTs.push(new Date(pipeline.started_at).getTime());
    if (pipeline?.completed_at)
      allTs.push(new Date(pipeline.completed_at).getTime());
    if (allTs.length === 0) {
      return { startMs: 0, endMs: 0, durationMs: 0 };
    }
    const start = Math.min(...allTs);
    const end = Math.max(...allTs);
    return {
      startMs: start,
      endMs: end,
      durationMs: Math.max(end - start, 1),
    };
  }, [activity, pipeline]);

  const filtered = useMemo(() => {
    if (filter === "all") return activity;
    return activity.filter((e) => bucketOf(e) === filter);
  }, [activity, filter]);

  if (activity.length === 0) {
    return null;
  }

  return (
    <section className="mt-5 rounded-2xl border border-border-subtle bg-surface overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border-subtle font-mono text-[12px] text-text-muted flex-wrap">
        <div className="flex items-center gap-2.5">
          <Clock size={14} className="text-text-muted" />
          <span className="text-foreground font-semibold text-[13px]">活动</span>
          <span className="text-text-faint">·</span>
          <span>{activity.length} 个事件</span>
          {startMs > 0 && endMs > 0 && (
            <>
              <span className="text-text-faint">·</span>
              <span>
                {fmtTime(startMs)}{" "}
                <span className="text-text-faint">→</span>{" "}
                {fmtTime(endMs)}
              </span>
              <span className="text-text-faint">·</span>
              <span>{fmtDuration(Math.round(durationMs / 1000))}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {(["all", "agent", "tool", "system", "done"] as const).map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => setFilter(b)}
              className={cn(
                "inline-flex items-center gap-1.5 h-6 px-2 rounded-md text-[11px] font-mono border transition-colors",
                filter === b
                  ? "border-brand-ring text-foreground bg-brand-bg"
                  : "border-border-muted text-text-muted hover:text-foreground hover:bg-surface-hover",
              )}
            >
              <span
                className="size-1.5 rounded-full"
                style={{ background: filterDot(b) }}
              />
              {bucketLabel(b)}
            </button>
          ))}
        </div>
      </header>

      {/* Horizontal scroller. Inner rail gets a minWidth so events spread
          out comfortably even when timestamps are very close together. */}
      <div className="overflow-x-auto">
        <div
          className="relative px-6 pt-6 pb-6 min-h-[320px]"
          style={{
            minWidth: Math.max(filtered.length * 220 + 120, 720),
          }}
        >
          <div
            className="relative h-px bg-border-muted"
            style={{ marginTop: 120 }}
          >
            {filtered.map((e, i) => {
              const ts = Date.parse(e.timestamp);
              // Distribute events evenly across the rail so cards never
              // overlap regardless of how close their real timestamps are.
              // Clamp to 5%–95% so the first/last card (~180px wide) doesn't
              // get clipped by the scroll container edges.
              const pct =
                filtered.length > 1
                  ? 5 + (i / (filtered.length - 1)) * 90
                  : 50;
              const bucket = bucketOf(e);
              const isTop = i % 2 === 0;
              return (
                <div
                  key={i}
                  className="absolute top-0 -translate-x-1/2"
                  style={{ left: `${pct}%` }}
                >
                  <span
                    className="absolute -top-1.5 size-3 rounded-full border-2"
                    style={{
                      borderColor: "var(--color-surface)",
                      background: bucketDot(bucket),
                      boxShadow: `0 0 0 3px ${bucketRing(bucket)}`,
                    }}
                  />
                  <EventCard event={e} index={i + 1} top={isTop} />
                  {isTop ? (
                    <span className="absolute top-3 left-1/2 -translate-x-1/2 font-mono text-[10.5px] text-text-faint whitespace-nowrap">
                      {fmtTime(ts)}
                    </span>
                  ) : (
                    <span className="absolute -top-5 left-1/2 -translate-x-1/2 font-mono text-[10.5px] text-text-faint whitespace-nowrap">
                      {fmtTime(ts)}
                    </span>
                  )}
                </div>
              );
            })}
            {/* start/end labels removed — they collided with the first/last
                event time labels at the same position. */}
          </div>
        </div>
      </div>
    </section>
  );
}

function EventCard({
  event,
  index,
  top,
}: {
  event: ActivityEvent;
  index: number;
  top: boolean;
}) {
  const bucket = bucketOf(event);
  const tone = cardTone(bucket);
  return (
    <div
      className={cn(
        "absolute left-1/2 -translate-x-1/2 w-[180px] px-2.5 py-2 rounded-lg border text-left",
        top ? "bottom-3 mb-2.5" : "top-3 mt-2.5",
      )}
      style={{
        borderColor: tone.border,
        background: tone.bg,
      }}
    >
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className="font-mono text-[10px] tabular-nums"
          style={{ color: tone.text }}
        >
          {circledNumber(index)}
        </span>
        <span
          className="font-mono text-[10.5px] uppercase tracking-[0.08em] font-semibold truncate"
          style={{ color: tone.text }}
        >
          {event.actor}
        </span>
      </div>
      <div className="text-[12px] leading-snug text-foreground line-clamp-3">
        {event.text}
      </div>
      {event.aux && (
        <div className="font-mono text-[10px] text-text-faint mt-1 truncate">
          {event.aux}
        </div>
      )}
    </div>
  );
}

function bucketOf(e: ActivityEvent): Bucket {
  const t = e.type;
  if (t === "task_done") return "done";
  if (t.startsWith("task_") || t === "issue_created") {
    if (e.actor === "system") return "system";
    return "agent";
  }
  if (t.startsWith("audit_")) return "tool";
  return "agent";
}

function bucketLabel(b: "all" | Bucket): string {
  if (b === "all") return "All";
  if (b === "agent") return "Agent";
  if (b === "tool") return "Tool";
  if (b === "system") return "System";
  return "Done";
}

function filterDot(b: "all" | Bucket): string {
  if (b === "all") return "var(--color-text-muted)";
  return bucketDot(b);
}

function bucketDot(b: Bucket): string {
  if (b === "agent") return "var(--color-brand)";
  if (b === "tool") return "var(--color-status-tool)";
  if (b === "system") return "var(--color-status-info)";
  return "var(--color-status-done)";
}

function bucketRing(b: Bucket): string {
  if (b === "agent") return "var(--color-brand-bg)";
  if (b === "tool") return "var(--color-tool-bg)";
  if (b === "system") return "var(--color-info-bg)";
  return "var(--color-done-bg)";
}

function cardTone(b: Bucket): { bg: string; border: string; text: string } {
  if (b === "agent")
    return {
      bg: "var(--color-brand-bg)",
      border: "var(--color-brand-ring)",
      text: "var(--color-brand)",
    };
  if (b === "tool")
    return {
      bg: "var(--color-tool-bg)",
      border: "var(--color-tool-ring)",
      text: "var(--color-status-tool)",
    };
  if (b === "system")
    return {
      bg: "var(--color-info-bg)",
      border: "var(--color-info-ring)",
      text: "var(--color-status-info)",
    };
  return {
    bg: "var(--color-done-bg)",
    border: "var(--color-done-ring)",
    text: "var(--color-status-done)",
  };
}

const CIRCLED = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];
function circledNumber(i: number): string {
  return CIRCLED[i - 1] ?? `${i}.`;
}

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const r = seconds % 60;
  if (m < 60) return r ? `${m}m ${String(r).padStart(2, "0")}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
