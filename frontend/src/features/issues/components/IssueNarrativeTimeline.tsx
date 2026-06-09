"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, XCircle, Clock, Pause, ChevronRight } from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { getCodexTasks } from "@/lib/api";
import type { CodexTask } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

interface Props {
  issueId: string;
  /** Reactive trigger from parent — when the parent's `issue.updated_at`
   * flips, the timeline pulls fresh tasks. Optional. */
  reloadKey?: string | number;
}

interface Entry {
  role: string;
  label: string;
  status: string;
  timestamp: string | null;
  summary: string;
}

const ROLE_ORDER = ["product_manager", "architect", "engineer", "qa"] as const;
const ROLE_LABEL: Record<string, string> = {
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  qa: "QA",
};

/**
 * Horizontal narrative of the issue's run, distilled from each role's
 * task.result JSON. No extra LLM call — just deterministic extraction of
 * the prose fields the agents already emit (requirement_analysis,
 * architecture_summary, summary, final_recommendation, etc).
 *
 *   PM 13:28 ✓ "3 acceptance criteria"
 *   →  Architect 13:30 ✓ "5 components, 2 risks"
 *   →  Engineer 13:36 ✓ "2 files changed"
 *   →  QA 13:40 ✓ "1 cmd run, passed"
 */
export function IssueNarrativeTimeline({ issueId, reloadKey }: Props) {
  const [tasks, setTasks] = useState<CodexTask[]>([]);

  const refresh = useCallback(async () => {
    try {
      const ts = await getCodexTasks(null, issueId);
      setTasks(ts);
    } catch {
      // best-effort
    }
  }, [issueId]);

  useEffect(() => {
    void refresh();
  }, [refresh, reloadKey]);

  // Direct event subscription so the timeline doesn't wait on the parent's
  // issue.updated_at poll to bubble down. Refreshes on task lifecycle.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("task_status", "task_created", "workflow_node_updated"),
    ),
    onEvent: () => { void refresh(); },
    throttleMs: 500,
  });

  const entries: Entry[] = useMemo(() => {
    const byRole: Record<string, CodexTask | undefined> = {};
    for (const t of tasks) {
      if (t.role && !byRole[t.role]) byRole[t.role] = t;
    }
    return ROLE_ORDER.filter((r) => byRole[r]).map((r) => {
      const t = byRole[r]!;
      return {
        role: r,
        label: ROLE_LABEL[r] ?? r,
        status: t.status ?? "pending",
        timestamp: t.updated_at ?? t.created_at ?? null,
        summary: deriveSummary(r, t.result || "", t.status ?? ""),
      };
    });
  }, [tasks]);

  if (entries.length === 0) return null;

  return (
    <div className="flex items-center gap-1 mt-3 px-8 max-w-6xl mx-auto w-full overflow-x-auto pb-1 scrollbar-none shrink-0">
      {entries.map((e, i) => {
        const isActiveRole = e.status === "running" || e.status === "responding";
        return (
          <div key={e.role} className="flex items-center shrink-0">
            <div
              data-density={isActiveRole ? "issue-narrative-active-role" : "issue-narrative-role"}
              className={cn(
                "relative min-w-[180px] max-w-[220px] flex flex-col gap-0.5 overflow-hidden px-3.5 py-1.5 rounded-xl border transition-all duration-300",
                e.status === "done"
                  ? "border-success/30 bg-success/5 shadow-sm"
                  : e.status === "failed"
                    ? "border-error/30 bg-error/5 shadow-sm"
                    : isActiveRole
                      ? "motion-essential border-brand/40 bg-brand/5 shadow-sm shadow-brand/10"
                      : "border-border-subtle bg-surface hover:bg-surface-hover"
              )}
            >
              {isActiveRole ? (
                <span
                  aria-hidden
                  className="motion-essential pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
                />
              ) : null}
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider">
                <StatusIcon status={e.status} />
                <span className={cn(
                  "font-bold",
                  e.status === "done" ? "text-success/90" : e.status === "failed" ? "text-error/90" : isActiveRole ? "text-brand" : "text-text-muted"
                )}>{e.label}</span>
                {e.timestamp && (
                  <span className="ml-auto tabular-nums text-text-muted/60 font-mono text-[10px]">{shortTime(e.timestamp)}</span>
                )}
              </div>
              <div
                className="text-[12px] font-medium text-foreground/80 line-clamp-2 leading-snug"
                title={e.summary}
              >
                {e.summary}
              </div>
            </div>
            {i < entries.length - 1 && (
              <div className="mx-2 flex items-center justify-center">
                <ChevronRight size={16} strokeWidth={2.5} className={e.status === "done" ? "text-success/40" : "text-border-subtle"} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 size={12} className="text-success" />;
  if (status === "failed") return <XCircle size={12} className="text-error" />;
  if (status === "running" || status === "responding")
    return <AgentThinkingIndicator phase="dispatching" size={12} />;
  if (status === "awaiting_review")
    return <Pause size={12} className="text-warning" />;
  return <Clock size={12} className="text-text-muted" />;
}

function shortTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/** Pull the most informative 1-2 line summary out of each role's
 * structured JSON result. Falls back to a status-based hint if the
 * result isn't JSON or the role hasn't reached terminal state. */
function deriveSummary(role: string, result: string, status: string): string {
  if (!result) {
    return statusHint(status);
  }
  let payload: Record<string, unknown> | null = null;
  // task.result may be a "summary string" (post-persist) or raw JSON
  // (pre-persist). Try JSON first, fall back to the string.
  try {
    payload = JSON.parse(result);
  } catch {
    payload = null;
  }

  switch (role) {
    case "product_manager":
      if (payload) {
        const criteria = arrayLen(payload, "acceptance_criteria");
        const goals = arrayLen(payload, "product_goals");
        const reqs = arrayLen(payload, "requirement_pool");
        const parts = [];
        if (criteria) parts.push(`${criteria} acceptance ${criteria === 1 ? "criterion" : "criteria"}`);
        if (goals) parts.push(`${goals} goal${goals === 1 ? "" : "s"}`);
        if (reqs) parts.push(`${reqs} req${reqs === 1 ? "" : "s"}`);
        if (parts.length) return parts.join(" · ");
      }
      return shortenResult(result);
    case "architect":
      if (payload) {
        const components = arrayLen(payload, "components");
        const data_models = arrayLen(payload, "data_models");
        const risks = arrayLen(payload, "risks");
        const parts = [];
        if (components) parts.push(`${components} component${components === 1 ? "" : "s"}`);
        if (data_models) parts.push(`${data_models} model${data_models === 1 ? "" : "s"}`);
        if (risks) parts.push(`${risks} risk${risks === 1 ? "" : "s"}`);
        if (parts.length) return parts.join(" · ");
      }
      return shortenResult(result);
    case "engineer":
      if (payload) {
        const files = arrayLen(payload, "changed_files");
        const st = String(payload.status ?? "");
        if (files || st) {
          const parts = [];
          if (st) parts.push(st);
          if (files) parts.push(`${files} file${files === 1 ? "" : "s"} changed`);
          return parts.join(" · ");
        }
      }
      return shortenResult(result);
    case "qa":
      if (payload) {
        const cmds = arrayLen(payload, "commands_run");
        const bugs = arrayLen(payload, "bugs_found");
        const st = String(payload.status ?? "");
        if (st || cmds || bugs) {
          const parts = [];
          if (st) parts.push(st);
          if (cmds) parts.push(`${cmds} cmd${cmds === 1 ? "" : "s"}`);
          if (bugs) parts.push(`${bugs} bug${bugs === 1 ? "" : "s"}`);
          return parts.join(" · ");
        }
      }
      return shortenResult(result);
  }
  return shortenResult(result);
}

function arrayLen(payload: Record<string, unknown>, key: string): number {
  const v = payload[key];
  return Array.isArray(v) ? v.length : 0;
}

function shortenResult(s: string): string {
  return s.length <= 80 ? s : s.slice(0, 77) + "…";
}

function statusHint(status: string): string {
  switch (status) {
    case "pending":
      return "Queued";
    case "running":
    case "responding":
      return "Working…";
    case "awaiting_review":
      return "Awaiting clarification";
    case "failed":
      return "Failed";
    default:
      return status || "—";
  }
}
