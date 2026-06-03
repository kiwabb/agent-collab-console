"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getIssueBudget } from "@/lib/api";
import type { IssueBudgetStatus } from "@/lib/types";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

/**
 * Live status of a per-issue budget.
 *
 * Three update paths, in priority order:
 *   1. WS `budget_warning` / `budget_exceeded` events for this issue → instant
 *      patch from the event payload (no extra request).
 *   2. Mount fetch + 30s poll while the issue is active (running/awaiting),
 *      to cover the happy-path growth between events.
 *   3. After a manual `refresh()` (e.g. the issue's other side-stack data
 *      reloaded) the latest snapshot wins.
 *
 * The hook never polls when the issue is done/idle — once the conductor
 * finalises, the meter just sits at its last value.
 */
export function useIssueBudget(
  issueId: string,
  isActive: boolean,
): { budget: IssueBudgetStatus | null; loading: boolean; refresh: () => void } {
  const [budget, setBudget] = useState<IssueBudgetStatus | null>(null);
  const [loading, setLoading] = useState(true);

  // Stable refs for the poll loop so the interval can be reset safely.
  const issueIdRef = useRef(issueId);
  issueIdRef.current = issueId;

  const fetchOnce = useCallback(async () => {
    // getIssueBudget swallows HTTP !ok to null, but a real network error
    // (fetch reject, JSON parse fail) would propagate. Without a catch
    // here, that leaves the hook in a perpetual `loading: true` state
    // and the meter would stay on the "..." placeholder forever.
    // Treat any thrown error as "no data" so the meter degrades to the
    // empty state instead.
    let next: IssueBudgetStatus | null = null;
    try {
      next = await getIssueBudget(issueIdRef.current);
    } catch (err) {
      // Guard against late responses after the issue unmounts.
      if (issueIdRef.current === issueId) {
        console.error(`useIssueBudget(${issueId}) fetch failed:`, err);
        setBudget(null);
        setLoading(false);
      }
      return;
    }
    // Guard against late responses after the issue unmounts.
    if (issueIdRef.current === issueId) {
      setBudget(next);
      setLoading(false);
    }
  }, [issueId]);

  // Mount fetch + manual refresh hook.
  const refresh = useCallback(() => {
    void fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    setLoading(true);
    void fetchOnce();
  }, [fetchOnce]);

  // Live update from WS steering events. The payload already carries the full
  // snapshot, so we just adapt it into the typed shape (the backend uses
  // snake_case keys, the API types use snake_case too — they match).
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("budget_warning", "budget_exceeded"),
    ),
    onEvent: (event) => {
      const evt = event as unknown as IssueBudgetStatus & { type: string };
      // Payload already matches the snapshot shape.
      setBudget({
        issue_id: evt.issue_id,
        spent_usd: evt.spent_usd,
        budget_usd: evt.budget_usd,
        remaining_usd: evt.remaining_usd,
        used_ratio: evt.used_ratio,
        soft_warn: evt.soft_warn ?? evt.type === "budget_warning",
        over_budget: evt.over_budget ?? evt.type === "budget_exceeded",
        soft_warn_ratio: evt.soft_warn_ratio ?? 0.8,
        has_ceiling: evt.has_ceiling ?? true,
        budget_source: evt.budget_source ?? "issue",
      });
    },
  });

  // Cheap happy-path poll: ONLY while the issue is active. The conductor emits
  // steering events at soft-warn/over-budget, but plain spend growth below
  // those thresholds has no event source — a 30s tick keeps the bar honest.
  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(() => {
      void fetchOnce();
    }, 30_000);
    return () => clearInterval(id);
  }, [isActive, fetchOnce]);

  return { budget, loading, refresh };
}
