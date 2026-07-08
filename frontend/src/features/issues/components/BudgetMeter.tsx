"use client";

import type { IssueBudgetStatus } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";

/**
 * Visual states for the budget meter. The mapping from a status snapshot to
 * a state is exported as `deriveBudgetMeterState` so it can be unit-tested
 * without React.
 */
export type BudgetMeterState = "over" | "soft_warn" | "healthy" | "unlimited" | "empty";

export interface BudgetMeterDerived {
  state: BudgetMeterState;
  /** 0..1 fill ratio for the bar. Always 0 in `unlimited` / `empty` so the bar never lies. */
  fillRatio: number;
  /** Whole-number percent for the badge. null in `unlimited` / `empty`. */
  percent: number | null;
  /** Tone class hook so the parent can apply it to surrounding chrome. */
  toneClass: string;
}

/**
 * Pure state derivation — no React, no DOM. The frontend unit test imports
 * this directly to pin the threshold behavior.
 */
export function deriveBudgetMeterState(status: IssueBudgetStatus | null): BudgetMeterDerived {
  if (!status) {
    return { state: "empty", fillRatio: 0, percent: null, toneClass: "text-text-muted" };
  }
  if (!status.has_ceiling) {
    return {
      state: "unlimited",
      fillRatio: 0,
      percent: null,
      toneClass: "text-text-muted",
    };
  }
  const ratio = Math.max(0, Math.min(1, status.used_ratio ?? 0));
  const percent = Math.round(ratio * 100);
  if (status.over_budget) {
    return {
      state: "over",
      fillRatio: 1,
      percent,
      toneClass: "text-status-failed",
    };
  }
  if (status.soft_warn || ratio >= status.soft_warn_ratio) {
    return {
      state: "soft_warn",
      fillRatio: ratio,
      percent,
      toneClass: "text-status-awaiting",
    };
  }
  return {
    state: "healthy",
    fillRatio: ratio,
    percent,
    toneClass: "text-status-done",
  };
}

/** Format a USD amount with up to 4 decimals, trimming trailing zeros. */
function fmtUsd(amount: number): string {
  if (amount === 0) return "0";
  if (amount < 0.01) return amount.toFixed(4);
  if (amount < 1) return amount.toFixed(3);
  return amount.toFixed(2);
}

interface Props {
  status: IssueBudgetStatus | null;
  loading?: boolean;
}

/**
 * The pure-presentation budget meter used in `IssueSideStack`. Renders one of
 * four states (over / soft_warn / healthy / unlimited) with color-coded
 * chrome; the bar is hidden in the unlimited branch by design (no ceiling →
 * no progress bar that could mislead).
 */
export function BudgetMeter({ status, loading }: Props) {
  const { t } = useI18n();
  const derived = deriveBudgetMeterState(status);

  if (loading && !status) {
    return (
      <div className="px-3.5 pb-3.5 text-[11px] font-mono text-text-faint">
        {t("issue.side.budget")} · …
      </div>
    );
  }

  return (
    <div className="px-3.5 pb-3.5">
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={cn(
            "font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold",
            derived.toneClass,
          )}
        >
          {t("issue.side.budget")} · {meterBadge(derived, t)}
        </span>
        {status && status.has_ceiling && derived.percent != null && (
          <span className={cn("font-mono text-[11px] font-black tabular-nums", derived.toneClass)}>
            {derived.percent}%
          </span>
        )}
      </div>

      <div className="mt-1.5 flex items-baseline gap-1.5 font-mono">
        {status ? (
          <>
            <span className="text-[18px] font-black text-foreground tabular-nums leading-none">
              ${fmtUsd(status.spent_usd)}
            </span>
            {status.has_ceiling ? (
              <>
                <span className="text-[11px] text-text-muted font-normal">
                  {t("issue.side.budgetOf", { budget: `$${fmtUsd(status.budget_usd)}` })}
                </span>
                {status.remaining_usd != null && (
                  <span className="text-[11px] text-text-faint ml-auto">
                    {t("issue.side.budgetRemaining", {
                      remaining: `$${fmtUsd(Math.max(0, status.remaining_usd))}`,
                    })}
                  </span>
                )}
              </>
            ) : (
              <span className="text-[11px] text-text-faint ml-auto">
                {t("issue.side.budgetUnlimited")}
              </span>
            )}
          </>
        ) : (
          <span className="text-[12px] text-text-muted">—</span>
        )}
      </div>

      {status && status.has_ceiling && (
        <div
          className="mt-2 h-1.5 bg-surface-input rounded-full overflow-hidden"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={derived.percent ?? 0}
        >
          <span
            className={cn(
              "block h-full rounded-full transition-all duration-500",
              derived.state === "over" && "bg-status-failed",
              derived.state === "soft_warn" && "bg-status-awaiting",
              derived.state === "healthy" && "bg-status-done",
            )}
            style={{
              width: `${Math.round(derived.fillRatio * 100)}%`,
              boxShadow:
                derived.state === "over"
                  ? "0 0 10px -2px color-mix(in srgb, var(--color-status-failed) 60%, transparent)"
                  : derived.state === "soft_warn"
                    ? "0 0 10px -2px color-mix(in srgb, var(--color-status-awaiting) 60%, transparent)"
                    : "0 0 8px -2px color-mix(in srgb, var(--color-status-done) 50%, transparent)",
            }}
          />
        </div>
      )}
    </div>
  );
}

type TFn = (key: string, params?: Record<string, string>) => string;

function meterBadge(derived: BudgetMeterDerived, t: TFn): string {
  switch (derived.state) {
    case "over":
      return t("issue.side.budgetOver");
    case "soft_warn":
      return t("issue.side.budgetSoftWarn", { pct: String(derived.percent ?? 0) });
    case "healthy":
      return t("issue.side.budgetHealthy");
    case "unlimited":
      return t("issue.side.budgetUnlimited");
    default:
      return "—";
  }
}
