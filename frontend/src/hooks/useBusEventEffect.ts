"use client";

import { useEffect, useRef } from "react";
import { useExecutionProcessesContext, type BusEvent } from "@/contexts/ExecutionProcessesContext";

interface Options {
  /** Return true to invoke onEvent for this event. */
  match: (event: BusEvent) => boolean;
  /** Called when an event passes match. Use deps to refresh the closure. */
  onEvent: (event: BusEvent) => void;
  /** Minimum ms between invocations. The trailing event wins. Defaults to 0 = no throttle. */
  throttleMs?: number;
  /** When false, the subscription is paused (e.g. inactive tab). */
  enabled?: boolean;
}

/**
 * Subscribe to the workspace event bus and call `onEvent` whenever a matching
 * BusEvent arrives. Reads `lastEvent` from ExecutionProcessesContext, so the
 * component tree must be inside a WorkbenchShell with workspaceId set.
 *
 * Stale-closure-safe: `match` / `onEvent` are stored in refs and re-read on
 * every event tick, so callers don't have to memoize them.
 *
 * Throttle is per-mount and uses a setTimeout to deliver the trailing event,
 * matching the "issue cards burst when scheduler runs three settles in 200ms"
 * shape we see in the wild.
 */
export function useBusEventEffect({ match, onEvent, throttleMs = 0, enabled = true }: Options): void {
  const { lastEvent } = useExecutionProcessesContext();
  const matchRef = useRef(match);
  const onEventRef = useRef(onEvent);
  matchRef.current = match;
  onEventRef.current = onEvent;

  const lastFiredAtRef = useRef(0);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingEventRef = useRef<BusEvent | null>(null);

  useEffect(() => {
    if (!enabled || !lastEvent) return;
    if (!matchRef.current(lastEvent)) return;

    if (throttleMs <= 0) {
      onEventRef.current(lastEvent);
      return;
    }

    const now = Date.now();
    const elapsed = now - lastFiredAtRef.current;
    if (elapsed >= throttleMs) {
      lastFiredAtRef.current = now;
      onEventRef.current(lastEvent);
      return;
    }

    pendingEventRef.current = lastEvent;
    if (pendingTimerRef.current) return;
    pendingTimerRef.current = setTimeout(() => {
      pendingTimerRef.current = null;
      const evt = pendingEventRef.current;
      pendingEventRef.current = null;
      if (!evt) return;
      lastFiredAtRef.current = Date.now();
      onEventRef.current(evt);
    }, throttleMs - elapsed);
  }, [lastEvent, enabled, throttleMs]);

  useEffect(() => {
    return () => {
      if (pendingTimerRef.current) {
        clearTimeout(pendingTimerRef.current);
        pendingTimerRef.current = null;
      }
    };
  }, []);
}

/** Convenience helpers for the most common matchers. */
export const busEventMatchers = {
  issueId: (issueId: string | null | undefined) => (event: BusEvent): boolean => {
    if (!issueId) return false;
    const evt = event as { issue_id?: string; task?: { issue_id?: string } };
    return evt.issue_id === issueId || evt.task?.issue_id === issueId;
  },
  taskId: (taskId: string | null | undefined) => (event: BusEvent): boolean => {
    if (!taskId) return false;
    const evt = event as { task_id?: string; task?: { id?: string } };
    return evt.task_id === taskId || evt.task?.id === taskId;
  },
  workspaceId: (workspaceId: string | null | undefined) => (event: BusEvent): boolean => {
    if (!workspaceId) return false;
    const evt = event as { session_id?: string; workspace_id?: string; task?: { session_id?: string } };
    return evt.session_id === workspaceId || evt.workspace_id === workspaceId || evt.task?.session_id === workspaceId;
  },
  typeIn: (...types: string[]) => {
    const set = new Set(types);
    return (event: BusEvent): boolean => set.has((event as { type?: string }).type ?? "");
  },
  all: (...predicates: Array<(event: BusEvent) => boolean>) => (event: BusEvent): boolean =>
    predicates.every((p) => p(event)),
};
