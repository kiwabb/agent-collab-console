"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import {
  BarChart3,
  LayoutGrid,
  Code2,
  ShieldCheck,
  AudioWaveform,
  Palette,
  Server,
  type LucideIcon,
} from "lucide-react";
import { useRoleStatus } from "@/features/agents/dock/AgentStatusProvider";
import type { RoleId } from "@/features/agents/dock/personas";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { cn } from "@/lib/utils";
import { useI18n } from "@/providers/I18nProvider";

export interface AgentDagNodeStats {
  tokens: { input: number; output: number; total: number } | null;
  duration_seconds: number | null;
  tools: string[];
  est_cost_usd: number | null;
  summary_stats?: { num: number; label: string; tone?: "good" | "bad" | null }[];
}

export interface AgentDagNodeData {
  role: RoleId;
  /** The DAG node title (used as fallback label when status is empty). */
  label: string;
  /** Persisted workflow node status, if this represents a real graph node. */
  status?: string;
  /** Backing task id, if any. */
  task_id?: string | null;
  /** True for the synthetic Conductor virtual root. */
  isConductor?: boolean;
  /** Original DAG node_key for click-through routing. */
  node_key: string;
  /** Per-node telemetry from /graph-stats (tokens / duration / tools). */
  stats?: AgentDagNodeStats | null;
  /** Optional click handler injected by the graph view. */
  onClick?: (payload: {
    node_key: string;
    task_id: string | null;
    status: string | null;
  }) => void;
}

const ROLE_ICON: Record<string, LucideIcon> = {
  conductor: AudioWaveform,
  product_manager: BarChart3,
  architect: LayoutGrid,
  engineer: Code2,
  engineer_frontend: Palette,
  engineer_backend: Server,
  qa: ShieldCheck,
};

const ROLE_LABEL: Record<string, string> = {
  conductor: "Conductor",
  product_manager: "PM",
  architect: "Architect",
  engineer: "Engineer",
  engineer_frontend: "FE Engineer",
  engineer_backend: "BE Engineer",
  qa: "QA",
};

const ROLE_TAGLINE_KEY: Record<string, string> = {
  conductor: "role.conductor",
  product_manager: "issue.stage.summary.pm",
  architect: "issue.stage.summary.architect",
  engineer: "issue.stage.summary.engineer",
  engineer_frontend: "role.engineer_frontend",
  engineer_backend: "role.engineer_backend",
  qa: "issue.stage.summary.qa",
};

/**
 * ReactFlow custom node — matches the Design handoff's dn-* card spec
 * (header bar + role tagline + body stats + footer meta).
 *
 * Visual tone:
 *   - start  → brand orange border + glow (Conductor + currently-running)
 *   - done   → green border + halo
 *   - failed → red border
 *   - idle   → muted surface
 *
 * Live status from AgentStatusProvider wins over the persisted node
 * status when the role is currently active.
 */
function AgentDagNodeImpl({ data }: NodeProps<AgentDagNodeData>) {
  const { t } = useI18n();
  const live = useRoleStatus(data.role);
  const tone = resolveTone(data, live.isActive);
  const Icon = ROLE_ICON[data.role] ?? Code2;
  const roleLabel = ROLE_LABEL[data.role] ?? data.label;
  const roleTaglineKey = ROLE_TAGLINE_KEY[data.role];
  const roleTagline = roleTaglineKey ? t(roleTaglineKey) : "";
  const statusText = humanStatus(data.status, live.status.text);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() =>
        data.onClick?.({
          node_key: data.node_key,
          task_id: data.task_id ?? null,
          status: data.status ?? null,
        })
      }
      className={cn(
        "relative w-[170px] overflow-hidden rounded-xl cursor-pointer transition-transform",
        "hover:-translate-y-px",
      )}
      style={{
        background: tone.bg,
        border: `1px solid ${tone.border}`,
        boxShadow: tone.shadow,
      }}
    >
      {/* Left handle (target). Conductor has no inputs. */}
      {!data.isConductor && (
        <Handle
          type="target"
          position={Position.Left}
          style={{ opacity: 0 }}
          isConnectable={false}
        />
      )}

      {/* === dn-head === */}
      <div
        className="flex items-center gap-2 px-2.5 py-2 border-b border-border-subtle"
        style={{
          background:
            "linear-gradient(180deg, rgba(255,255,255,0.02), transparent)",
        }}
      >
        <span
          className="shrink-0 size-[26px] rounded-[7px] flex items-center justify-center"
          style={{ background: tone.iconBg, color: tone.text }}
        >
          <Icon size={14} strokeWidth={2} />
        </span>
        <span
          className="font-mono text-[10.5px] uppercase tracking-[0.1em] font-semibold flex-1 leading-none"
          style={{ color: tone.text }}
        >
          {roleLabel}
        </span>
        <StatusDot mode={tone.mode} />
      </div>

      {/* === dn-role === */}
      {(roleTagline || data.label) && (
        <div className="px-2.5 pt-2 pb-1.5 text-[12px] text-text-secondary border-b border-border-subtle border-dashed">
          {roleTagline}
          {data.label && data.label !== roleLabel && (
            <>
              {" · "}
              <b className="text-foreground font-medium">{data.label}</b>
            </>
          )}
        </div>
      )}

      {/* === dn-body: per-role num + lbl stat rows (design handoff) === */}
      <div className="px-2.5 pt-2 pb-1.5 flex flex-col gap-1">
        {data.stats?.summary_stats?.length ? (
          data.stats.summary_stats.map((s, i) => (
            <div
              key={`${s.label}-${i}`}
              className="flex items-baseline gap-1.5 text-[12px] text-text-secondary"
            >
              <span
                className={cn(
                  "font-mono text-[14px] font-semibold tabular-nums leading-none tracking-tight min-w-[32px]",
                  s.tone === "good"
                    ? "text-status-done"
                    : s.tone === "bad"
                      ? "text-status-failed"
                      : "text-foreground",
                )}
              >
                {s.label === "added" && s.num > 0
                  ? `+${s.num}`
                  : s.label === "removed" && s.num > 0
                    ? `−${s.num}`
                    : s.num}
              </span>
              <span className="text-[11px] text-text-muted">{s.label}</span>
            </div>
          ))
        ) : (
          <div className="flex items-baseline gap-1.5 text-[12px] text-text-secondary">
            <span className="text-[11px] text-text-muted">status</span>
            <span
              className="font-mono text-[13px] font-semibold leading-none tracking-tight"
              style={{ color: tone.text }}
            >
              {statusText}
            </span>
          </div>
        )}
      </div>

      {/* === dn-tools chips === */}
      {data.stats?.tools && data.stats.tools.length > 0 && (
        <div className="px-2.5 py-1.5 flex flex-wrap gap-1 border-t border-border-subtle border-dashed">
          {data.stats.tools.slice(0, 4).map((tool) => (
            <span
              key={tool}
              className="font-mono text-[10px] text-text-muted bg-surface-input border border-border-subtle px-1.5 leading-[14px] rounded"
            >
              {tool}
            </span>
          ))}
          {data.stats.tools.length > 4 && (
            <span className="font-mono text-[10px] text-text-muted bg-surface-input border border-border-subtle px-1.5 leading-[14px] rounded">
              +{data.stats.tools.length - 4}
            </span>
          )}
        </div>
      )}

      {/* === dn-foot: duration + tokens === */}
      <div
        className="flex items-center justify-between px-2.5 py-1.5 font-mono text-[10.5px] border-t border-border-subtle"
        style={{ background: "rgba(0,0,0,0.18)" }}
      >
        <span className="text-text-secondary truncate">
          {data.stats?.duration_seconds != null
            ? fmtDuration(data.stats.duration_seconds)
            : tone.footTag}
        </span>
        <span className="text-text-muted truncate">
          {data.stats?.est_cost_usd != null
            ? `$${data.stats.est_cost_usd.toFixed(3)}`
            : data.task_id
              ? `task ${data.task_id.slice(0, 6)}`
              : "—"}
        </span>
      </div>

      {/* Right handle (source) */}
      <Handle
        type="source"
        position={Position.Right}
        style={{ opacity: 0 }}
        isConnectable={false}
      />
    </div>
  );
}

function StatusDot({
  mode,
}: {
  mode: "done" | "running" | "failed" | "idle" | "awaiting" | "start";
}) {
  if (mode === "running") {
    return <AgentThinkingIndicator phase="dispatching" size={10} />;
  }

  const color =
    mode === "done"
      ? "var(--color-status-done)"
      : mode === "start"
        ? "var(--color-brand)"
        : mode === "failed"
          ? "var(--color-status-failed)"
          : mode === "awaiting"
            ? "var(--color-status-awaiting)"
            : "var(--color-text-faint)";
  const ring =
    mode === "done"
      ? "var(--color-done-ring)"
      : mode === "start"
        ? "var(--color-brand-ring)"
        : mode === "failed"
          ? "var(--color-failed-ring)"
          : "transparent";
  return (
    <span
      className="shrink-0 size-[7px] rounded-full"
      style={{
        background: color,
        boxShadow: ring !== "transparent" ? `0 0 0 3px ${ring}` : undefined,
      }}
    />
  );
}

interface Tone {
  mode: "done" | "running" | "failed" | "idle" | "awaiting" | "start";
  bg: string;
  border: string;
  shadow: string;
  iconBg: string;
  text: string;
  footTag: string;
}

function resolveTone(data: AgentDagNodeData, isLiveActive: boolean): Tone {
  const status = (data.status ?? "").toLowerCase();
  const surfaceGradient =
    "linear-gradient(180deg, var(--color-surface-raised) 0%, var(--color-surface) 100%)";

  if (data.isConductor) {
    return {
      mode: "start",
      bg: surfaceGradient,
      border: "var(--color-brand-ring)",
      shadow:
        "0 12px 36px -10px rgba(0,0,0,0.7), 0 0 0 1px var(--color-brand-ring) inset, 0 0 40px -6px var(--color-brand-ring)",
      iconBg: "var(--color-brand-bg)",
      text: "var(--color-brand)",
      footTag: "auto-plan",
    };
  }
  if (isLiveActive || status === "running") {
    return {
      mode: "running",
      bg: surfaceGradient,
      border: "var(--color-brand-ring)",
      shadow:
        "0 12px 36px -10px rgba(0,0,0,0.7), 0 0 0 1px var(--color-brand-ring) inset, 0 0 40px -6px var(--color-brand-ring)",
      iconBg: "var(--color-brand-bg)",
      text: "var(--color-brand)",
      footTag: "running",
    };
  }
  if (status === "done" || status === "skipped") {
    return {
      mode: "done",
      bg: surfaceGradient,
      border: "var(--color-done-ring)",
      shadow:
        "0 12px 32px -10px rgba(0,0,0,0.7), 0 0 0 1px var(--color-done-ring) inset, 0 0 30px -8px color-mix(in srgb, var(--color-status-done) 20%, transparent)",
      iconBg: "color-mix(in srgb, var(--color-status-done) 14%, transparent)",
      text: "var(--color-status-done)",
      footTag: status === "skipped" ? "skipped" : "done",
    };
  }
  if (status === "failed" || status === "needs_rework") {
    return {
      mode: "failed",
      bg: surfaceGradient,
      border: "var(--color-failed-ring)",
      shadow:
        "0 12px 32px -10px rgba(0,0,0,0.7), 0 0 0 1px var(--color-failed-ring) inset",
      iconBg: "color-mix(in srgb, var(--color-status-failed) 14%, transparent)",
      text: "var(--color-status-failed)",
      footTag: status === "needs_rework" ? "rework" : "failed",
    };
  }
  if (status === "awaiting_review" || status === "awaiting_approval") {
    return {
      mode: "awaiting",
      bg: surfaceGradient,
      border:
        "color-mix(in srgb, var(--color-status-awaiting) 35%, transparent)",
      shadow:
        "0 12px 32px -10px rgba(0,0,0,0.7), 0 0 0 1px color-mix(in srgb, var(--color-status-awaiting) 18%, transparent) inset",
      iconBg:
        "color-mix(in srgb, var(--color-status-awaiting) 14%, transparent)",
      text: "var(--color-status-awaiting)",
      footTag: "awaiting",
    };
  }
  // pending / blocked / ready / unknown
  return {
    mode: "idle",
    bg: surfaceGradient,
    border: "var(--color-border-muted)",
    shadow: "0 12px 28px -14px rgba(0,0,0,0.5)",
    iconBg: "var(--color-surface-input)",
    text: "var(--color-text-secondary)",
    footTag: status === "ready" ? "ready" : "queued",
  };
}

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const r = seconds % 60;
  if (m < 60) return r ? `${m}m ${String(r).padStart(2, "0")}s` : `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function humanStatus(persisted: string | undefined, live: string): string {
  if (live) return live;
  switch (persisted) {
    case "pending":
    case "blocked":
      return "Waiting";
    case "ready":
      return "Up next";
    case "running":
      return "Running";
    case "done":
      return "Done";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    case "needs_rework":
      return "Rework";
    case "awaiting_review":
      return "Awaiting review";
    case "awaiting_approval":
      return "Awaiting approval";
    default:
      return persisted || "—";
  }
}

export const AgentDagNode = memo(AgentDagNodeImpl);
