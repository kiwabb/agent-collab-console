"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { PERSONAS, type RoleId } from "@/features/agents/dock/personas";
import { useRoleStatus } from "@/features/agents/dock/AgentStatusProvider";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";

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
  /** Optional click handler injected by the graph view. */
  onClick?: (payload: { node_key: string; task_id: string | null; status: string | null }) => void;
}

/**
 * ReactFlow custom node — renders a persona avatar + speech bubble in
 * place of the boring rectangle. Reads live status from the
 * AgentStatusProvider context.
 *
 * Size is fixed so ReactFlow's edge router doesn't jitter on the
 * breathing scale animation (the scale happens on an inner div inside
 * AgentTile, not on the bounding box).
 */
function AgentDagNodeImpl({ data }: NodeProps<AgentDagNodeData>) {
  const persona = PERSONAS[data.role] ?? PERSONAS.product_manager;
  const { status: liveStatus, isActive } = useRoleStatus(data.role);

  // For Conductor we always trust live status. For role nodes, if there's
  // no live activity, fall back to the persisted DAG node status so
  // already-done graphs still show their final state.
  const status = liveStatus.text
    ? liveStatus
    : {
        role: data.role,
        text: data.status ? labelFromStatus(data.status) : "",
        mode: modeFromStatus(data.status),
        tone: toneFromStatus(data.status),
      } as typeof liveStatus;

  const isDone = status.mode === "done";
  const isFailed = status.mode === "failed";
  const isWaiting = status.mode === "waiting";

  return (
    <motion.div
      className={cn(
        "relative flex flex-col p-3 rounded-2xl border shadow-sm cursor-pointer",
        isActive
          ? "border-transparent"
          : isDone
            ? "border-success/30 bg-success/5 backdrop-blur-md"
            : isFailed
              ? "border-error/30 bg-error/5 backdrop-blur-md"
              : "border-border-subtle hover:border-brand/50 bg-surface/90 backdrop-blur-md"
      )}
      style={{ width: 180 }}
      animate={{
        scale: isActive ? 1.05 : 1,
        y: isActive ? -4 : 0,
      }}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
      onClick={() =>
        data.onClick?.({
          node_key: data.node_key,
          task_id: data.task_id ?? null,
          status: data.status ?? null,
        })
      }
    >
      {/* Solid background to block the glow behind text in the stacking context */}
      {isActive && (
        <div className="absolute inset-0 rounded-2xl bg-surface z-0" />
      )}

      {/* Animated glowing border for active state */}
      {isActive && (
        <>
          <motion.div
            className="absolute -inset-[1.5px] rounded-[17.5px] -z-10 opacity-80"
            style={{
              background: `linear-gradient(90deg, ${persona.color}, #a855f7, ${persona.color})`,
              backgroundSize: "200% 200%",
            }}
            animate={{ backgroundPosition: ["0% 50%", "100% 50%", "0% 50%"] }}
            transition={{ duration: 3, ease: "linear", repeat: Infinity }}
          />
          <motion.div
            className="absolute -inset-[1.5px] rounded-[17.5px] -z-20 blur-md opacity-40"
            style={{
              background: `linear-gradient(90deg, ${persona.color}, #a855f7, ${persona.color})`,
              backgroundSize: "200% 200%",
            }}
            animate={{ backgroundPosition: ["0% 50%", "100% 50%", "0% 50%"] }}
            transition={{ duration: 3, ease: "linear", repeat: Infinity }}
          />
        </>
      )}

      {/* Left handle (target). Conductor has no inputs. */}
      {!data.isConductor && (
        <Handle
          type="target"
          position={Position.Left}
          style={{ opacity: 0 }}
          isConnectable={false}
        />
      )}

      {/* Content */}
      <div className="relative z-10 flex items-center gap-3">
        {/* Avatar */}
        <div
          className="relative shrink-0 flex items-center justify-center rounded-full bg-background border border-border-subtle shadow-sm z-10"
          style={{
            width: 42,
            height: 42,
            fontSize: 22,
            borderColor: isActive ? persona.color : undefined,
          }}
        >
          {persona.emoji}
          {isActive && (
            <span
              className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full border-2 border-background animate-pulse"
              style={{ backgroundColor: persona.color }}
            />
          )}
          {isDone && (
            <span className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full border-2 border-background bg-success" />
          )}
          {isFailed && (
            <span className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full border-2 border-background bg-error" />
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-text-muted truncate">
            {persona.name}
          </div>
          <div
            className={cn(
              "text-[12px] font-medium truncate mt-0.5",
              isActive
                ? "text-brand"
                : isDone
                  ? "text-success"
                  : isFailed
                    ? "text-error"
                    : "text-foreground"
            )}
            style={isActive ? { color: persona.color } : undefined}
          >
            {status.detail || status.text || "Pending"}
          </div>
        </div>
      </div>

      {/* Right handle (source) */}
      <Handle
        type="source"
        position={Position.Right}
        style={{ opacity: 0 }}
        isConnectable={false}
      />
    </motion.div>
  );
}

function labelFromStatus(s: string): string {
  switch (s) {
    case "pending":
    case "blocked":
      return "Waiting";
    case "ready":
      return "Up next";
    case "running":
      return "Working…";
    case "done":
      return "Done";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    default:
      return s;
  }
}

function modeFromStatus(s: string | undefined): "idle" | "active" | "done" | "failed" | "waiting" {
  switch (s) {
    case "running":
      return "active";
    case "done":
      return "done";
    case "failed":
      return "failed";
    case "pending":
    case "blocked":
    case "ready":
    case "skipped":
      return "waiting";
    default:
      return "idle";
  }
}

function toneFromStatus(s: string | undefined): "neutral" | "info" | "success" | "warning" | "error" {
  switch (s) {
    case "running":
      return "info";
    case "done":
      return "success";
    case "failed":
      return "error";
    default:
      return "neutral";
  }
}

export const AgentDagNode = memo(AgentDagNodeImpl);
