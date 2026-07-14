import { Loader2, SearchCode } from "lucide-react";

import type { PrototypePlan } from "@/lib/types";
import { prototypeAnalysisPercent, prototypeAnalysisPhaseKey } from "./prototypePlanReviewState";

interface Props {
  plan: PrototypePlan;
  t: (key: string, params?: Record<string, string | number>) => string;
}

export function PrototypeAnalysisProgress({ plan, t }: Props) {
  if (plan.status !== "queued" && plan.status !== "analyzing") return null;
  const percent = prototypeAnalysisPercent(plan.analysis_completed, plan.analysis_total);
  const hasBatches = plan.analysis_total > 0;
  return (
    <section
      className="relative overflow-hidden rounded-lg border border-status-awaiting/40 bg-status-awaiting/5 px-4 py-3"
      data-density="compact"
    >
      <div className="flex min-w-0 items-start gap-3">
        {plan.analysis_phase === "queued" ? (
          <SearchCode
            className="mt-0.5 shrink-0 text-status-awaiting"
            size={17}
            aria-hidden="true"
          />
        ) : (
          <Loader2
            className="motion-essential mt-0.5 shrink-0 animate-spin text-status-awaiting"
            size={17}
            aria-hidden="true"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold">{t("prototype.plan.analysisProgressTitle")}</h2>
              <p className="mt-0.5 text-xs text-text-muted">
                {t(prototypeAnalysisPhaseKey(plan.analysis_phase))}
              </p>
              {plan.analysis_phase === "planning" && plan.updated_at ? (
                <p className="mt-1 text-xs text-text-muted">
                  {t("prototype.plan.analysisLastActivity", {
                    time: new Date(plan.updated_at).toLocaleTimeString(),
                  })}
                </p>
              ) : null}
            </div>
            <span
              role="status"
              aria-live="polite"
              aria-atomic="true"
              className="font-mono text-xs tabular-nums text-text-muted"
            >
              {hasBatches
                ? t("prototype.plan.analysisBatches", {
                    completed: plan.analysis_completed,
                    total: plan.analysis_total,
                  })
                : t("prototype.plan.analysisPreparing")}
            </span>
          </div>
          <div
            className="mt-3 h-2 overflow-hidden rounded-sm bg-surface-base"
            role="progressbar"
            aria-label={t("prototype.plan.analysisProgressTitle")}
            aria-valuemin={0}
            aria-valuemax={hasBatches ? plan.analysis_total : 1}
            aria-valuenow={hasBatches ? plan.analysis_completed : 0}
            aria-valuetext={
              hasBatches
                ? t("prototype.plan.analysisBatches", {
                    completed: plan.analysis_completed,
                    total: plan.analysis_total,
                  })
                : t("prototype.plan.analysisPreparing")
            }
          >
            <div
              className="h-full bg-status-awaiting"
              style={{ width: `${hasBatches ? percent : 8}%` }}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
