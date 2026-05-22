"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Circle } from "lucide-react";
import { useWorkbenchStore } from "@/store/workbenchStore";
import { cn } from "@/lib/utils";

interface Props {
  issueId: string;
}

const TERMINAL_STATUSES = new Set(["done", "failed", "completed", "killed", "cancelled"]);

// Map raw role strings to short display labels
function roleLabel(role: string): string {
  const map: Record<string, string> = {
    pm: "PM",
    product_manager: "PM",
    architect: "Architect",
    engineer: "Engineer",
    developer: "Engineer",
    qa: "QA",
    qa_engineer: "QA",
    conductor: "Conductor",
  };
  return map[role.toLowerCase()] ?? role;
}

export function LiveThinkingDock({ issueId }: Props) {
  const dismissedKey = `live-thinking-dismissed:${issueId}`;
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [activeRole, setActiveRole] = useState<string | null>(null);
  // role → accumulated text buffer
  const [buffers, setBuffers] = useState<Record<string, string>>({});
  // roles that currently have an active (running) process
  const [runningRoles, setRunningRoles] = useState<Set<string>>(new Set());
  // roles that appeared at some point (so we keep their tabs until dismissed)
  const [seenRoles, setSeenRoles] = useState<string[]>([]);

  const scrollRef = useRef<HTMLPreElement>(null);

  const lastEvent = useWorkbenchStore((s) => s.lastEvent);
  const tasks = useWorkbenchStore((s) => s.tasks);

  useEffect(() => {
    setDismissed(window.sessionStorage.getItem(dismissedKey) === "1");
  }, [dismissedKey]);

  // ── React to incoming bus events ──────────────────────────────────────────
  useEffect(() => {
    if (!lastEvent) return;
    const evt = lastEvent as any;

    if (evt.type === "message_delta" && evt.task_id && evt.delta_text) {
      // Resolve the task's role from the store's task list, filtered to this issue
      const task = tasks.find(
        (t) => t.id === evt.task_id && t.issue_id === issueId,
      );
      // Also try without issue filter in case tasks aren't loaded yet
      const fallbackTask = tasks.find((t) => t.id === evt.task_id);
      const rawRole =
        (task ?? fallbackTask)?.role ?? "agent";
      const role = roleLabel(rawRole);

      setBuffers((prev) => ({
        ...prev,
        [role]: (prev[role] ?? "") + (evt.delta_text as string),
      }));
      setRunningRoles((prev) => new Set([...prev, role]));
      setSeenRoles((prev) =>
        prev.includes(role) ? prev : [...prev, role],
      );
      if (dismissed) {
        window.sessionStorage.removeItem(dismissedKey);
        setDismissed(false);
      }
      // Auto-open when first delta arrives
      setExpanded(true);
      setActiveRole((prev) => prev ?? role);
    }

    if (evt.type === "task_status" && evt.task_id) {
      const status = String(evt.status ?? "").toLowerCase();
      if (TERMINAL_STATUSES.has(status)) {
        const task = tasks.find(
          (t) => t.id === evt.task_id && t.issue_id === issueId,
        );
        const fallbackTask = tasks.find((t) => t.id === evt.task_id);
        const rawRole = (task ?? fallbackTask)?.role;
        if (rawRole) {
          const role = roleLabel(rawRole);
          setRunningRoles((prev) => {
            const next = new Set(prev);
            next.delete(role);
            return next;
          });
        }
      }
    }
  }, [lastEvent, tasks, issueId, dismissed, dismissedKey]);

  useEffect(() => {
    if (!expanded) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expanded]);

  // Auto-scroll to bottom when active tab's buffer grows
  useEffect(() => {
    if (expanded && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [expanded, activeRole, buffers]);

  // Auto-collapse when no roles are running
  useEffect(() => {
    if (runningRoles.size === 0 && expanded && seenRoles.length > 0) {
      // Keep open for a moment so user can read the final output
      const t = setTimeout(() => setExpanded(false), 4000);
      return () => clearTimeout(t);
    }
  }, [runningRoles.size, expanded, seenRoles.length]);

  // Nothing to show yet — render nothing until at least one delta arrives
  if (seenRoles.length === 0) return null;
  if (dismissed && runningRoles.size === 0) return null;

  const activeBuffer = activeRole ? (buffers[activeRole] ?? "") : "";

  return (
    <div
      aria-live="polite"
      aria-label="Live agent thinking stream"
      className={cn(
        "fixed bottom-3 left-3 right-3 z-50",
        "enterprise-panel rounded-[26px]",
        "transition-all duration-200 ease-in-out",
        expanded ? "h-[220px]" : "h-[40px]",
        "flex flex-col",
      )}
    >
      {/* ── Header bar ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-0 shrink-0 h-[40px] px-3 select-none">
        {/* Role tabs */}
        <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto">
          {seenRoles.map((role) => {
            const isRunning = runningRoles.has(role);
            const isActive = role === activeRole;
            return (
              <button
                key={role}
                type="button"
                onClick={() => {
                  setActiveRole(role);
                  setExpanded(true);
                }}
                className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-mono font-medium transition-colors shrink-0",
                  isActive
                    ? "bg-surface-raised text-foreground"
                    : "text-text-muted hover:text-foreground hover:bg-surface-raised/60",
                )}
              >
                {isRunning && (
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-brand opacity-75" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-brand" />
                  </span>
                )}
                {!isRunning && (
                  <Circle
                    size={6}
                    className="text-text-faint fill-current"
                  />
                )}
                {role}
              </button>
            );
          })}
        </div>

        {/* Collapse/expand toggle */}
        <button
          type="button"
          onClick={() => {
            window.dispatchEvent(
              new CustomEvent("open-conductor-log", { detail: { issueId } }),
            );
          }}
          className="ml-2 shrink-0 rounded-lg px-2 py-1 text-[11px] text-text-muted transition-colors hover:text-foreground"
        >
          Open log
        </button>
        {runningRoles.size === 0 && (
          <button
            type="button"
            onClick={() => {
              window.sessionStorage.setItem(dismissedKey, "1");
              setDismissed(true);
            }}
            className="shrink-0 rounded-lg px-2 py-1 text-[11px] text-text-muted transition-colors hover:text-foreground"
          >
            Dismiss
          </button>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-2 shrink-0 flex items-center gap-1 px-2 py-1 rounded-lg text-text-muted hover:text-foreground transition-colors text-[11px]"
          aria-label={expanded ? "Collapse thinking dock" : "Expand thinking dock"}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
          <span className="font-mono">
            {runningRoles.size > 0 ? "thinking…" : "done"}
          </span>
        </button>
      </div>

      {/* ── Streaming content area ──────────────────────────────────────────── */}
      {expanded && (
        <pre
          ref={scrollRef}
          className={cn(
            "flex-1 min-h-0 overflow-y-auto",
            "px-4 py-2",
            "font-mono text-[11px] leading-[1.55]",
            "text-text-secondary",
            "whitespace-pre-wrap break-words",
          )}
        >
          {activeBuffer || (
            <span className="text-text-faint italic">Waiting for agent output…</span>
          )}
          {runningRoles.has(activeRole ?? "") && (
            <span className="inline-block w-[7px] h-[11px] ml-0.5 bg-brand/80 animate-pulse align-middle" />
          )}
        </pre>
      )}
    </div>
  );
}
