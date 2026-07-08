"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getIssueBudget } from "@/lib/api/stats";
import type { IssueBudgetStatus } from "@/lib/types";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";

type BudgetSteeringEventType = "budget_warning" | "budget_exceeded";

interface BackendBudgetSteeringEventPayload {
  type: BudgetSteeringEventType;
  issue_id: string;
  spent_usd: number;
  budget_usd: number;
  remaining_usd: number | null;
  used_ratio: number | null;
  budget_source: "issue" | "default";
  soft_warn_ratio?: number;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function readNullableNumber(value: unknown): number | null | undefined {
  if (value === null) return null;
  return isFiniteNumber(value) ? value : undefined;
}

function isBudgetSource(value: unknown): value is "issue" | "default" {
  return value === "issue" || value === "default";
}

type UnknownRecord = { [key: string]: unknown };

function isUnknownRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBudgetSteeringEventPayload(
  value: unknown,
): value is BackendBudgetSteeringEventPayload {
  if (!isUnknownRecord(value)) return false;
  const type = value["type"];
  const issueId = value["issue_id"];
  const spentUsd = value["spent_usd"];
  const budgetUsd = value["budget_usd"];
  const remainingUsd = readNullableNumber(value["remaining_usd"]);
  const usedRatio = readNullableNumber(value["used_ratio"]);
  const budgetSource = value["budget_source"];
  const softWarnRatio = value["soft_warn_ratio"];

  if (type !== "budget_warning" && type !== "budget_exceeded") return false;
  if (typeof issueId !== "string") return false;
  if (!isFiniteNumber(spentUsd) || !isFiniteNumber(budgetUsd)) return false;
  if (remainingUsd === undefined || usedRatio === undefined) return false;
  if (!isBudgetSource(budgetSource)) return false;
  if (type === "budget_warning") return isFiniteNumber(softWarnRatio);
  return softWarnRatio === undefined || isFiniteNumber(softWarnRatio);
}

/**
 * Normalize backend budget steering events into the endpoint-shaped status used
 * by the meter. The backend intentionally emits a smaller WS payload than the
 * read endpoint: warning events include `soft_warn_ratio`, while exceeded
 * events omit it. Exceeded events have crossed the hard ceiling, so `1` is the
 * tightest safe threshold when no prior endpoint snapshot is available.
 */
export function readBudgetSteeringEvent(
  event: unknown,
): IssueBudgetStatus | null {
  if (!isBudgetSteeringEventPayload(event)) return null;
  const overBudget = event.type === "budget_exceeded";
  return {
    issue_id: event.issue_id,
    spent_usd: event.spent_usd,
    budget_usd: event.budget_usd,
    remaining_usd: event.remaining_usd,
    used_ratio: event.used_ratio,
    soft_warn: true,
    over_budget: overBudget,
    soft_warn_ratio: event.soft_warn_ratio ?? 1,
    has_ceiling: true,
    budget_source: event.budget_source,
  };
}

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

  const issueIdRef = useRef(issueId);
  issueIdRef.current = issueId;

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchOnce = useCallback(async () => {
    let next: IssueBudgetStatus | null = null;
    try {
      next = await getIssueBudget(issueIdRef.current);
    } catch (err) {
      if (mountedRef.current && issueIdRef.current === issueId) {
        console.error(`useIssueBudget(${issueId}) fetch failed:`, err);
        setBudget(null);
        setLoading(false);
      }
      return;
    }
    if (mountedRef.current && issueIdRef.current === issueId) {
      setBudget(next);
      setLoading(false);
    }
  }, [issueId]);

  const refresh = useCallback(() => {
    void fetchOnce();
  }, [fetchOnce]);

  useEffect(() => {
    setLoading(true);
    void fetchOnce();
  }, [fetchOnce]);

  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("budget_warning", "budget_exceeded"),
    ),
    onEvent: (event) => {
      if (!mountedRef.current) return;
      const next = readBudgetSteeringEvent(event);
      if (!next) return;
      setBudget((prev) =>
        prev && next.spent_usd < prev.spent_usd ? prev : next,
      );
    },
  });

  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(() => {
      void fetchOnce();
    }, 30_000);
    return () => clearInterval(id);
  }, [isActive, fetchOnce]);

  return { budget, loading, refresh };
}
