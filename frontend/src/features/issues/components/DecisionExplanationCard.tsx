"use client";

import { Info, Network } from "lucide-react";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import type { IssueOrchestrationPolicy } from "@/lib/types";
import { useI18n } from "@/providers/I18nProvider";
import { cn } from "@/lib/utils";
import {
  deriveDecisionExplanationView,
  type DecisionExplanationTone,
} from "./deriveDecisionExplanationView";

interface Props {
  policy: IssueOrchestrationPolicy | null;
  loading: boolean;
}

const TONE_CLASS: Record<DecisionExplanationTone, string> = {
  serial: "text-brand bg-brand-bg border-brand/20",
  parallel: "text-status-tool bg-status-tool/10 border-status-tool/25",
  clarify: "text-status-awaiting bg-status-awaiting/10 border-status-awaiting/25",
  review: "text-status-info bg-status-info/10 border-status-info/25",
};

export function DecisionExplanationCard({ policy, loading }: Props) {
  const { t } = useI18n();

  return (
    <section data-decision-explanation-panel className="enterprise-panel border-border-subtle/60 bg-surface/90 rounded-lg overflow-hidden hover:border-border-strong/45 transition-colors">
      <header className="px-3 py-2.5 flex items-center gap-2 border-b border-border-subtle/60 bg-surface-input/30">
        <Network size={15} className="text-brand shrink-0" />
        <span className="text-[13px] font-bold tracking-wide text-foreground">
          {t("issue.decision.title")}
        </span>
        <span className="ml-auto font-mono text-[9px] text-text-muted uppercase tracking-wider font-black bg-surface-input px-2.5 py-0.5 rounded border border-border-subtle/40">
          {t("issue.decision.sub")}
        </span>
      </header>

      {policy ? (
        <PolicyBody policy={policy} />
      ) : (
        <div
          className={cn(
            "px-4 py-4 text-[12px] leading-relaxed text-text-muted",
            loading && "motion-essential relative flex items-center gap-2 overflow-hidden",
          )}
        >
          {loading && (
            <>
              <span
                aria-hidden
                className="pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-brand/70 to-transparent"
              />
              <RoutingMotion isParallelRouting={false} />
            </>
          )}
          <span>{loading ? t("issue.decision.loading") : t("issue.decision.empty")}</span>
        </div>
      )}
    </section>
  );
}

function PolicyBody({ policy }: { policy: IssueOrchestrationPolicy }) {
  const { t } = useI18n();
  const view = deriveDecisionExplanationView(policy);
  const isParallelRouting = view.tone === "parallel" || policy.batch_allowed;
  return (
    <div className="p-2.5 space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <div
          data-density="decision-routing-intelligence"
          className={cn(
            "rounded-lg border border-border-subtle/50 bg-surface-input/35 p-2.5",
            isParallelRouting && "motion-essential relative overflow-hidden border-status-tool/30 bg-status-tool/10",
          )}
        >
          {isParallelRouting && (
            <span
              aria-hidden
              className="pointer-events-none absolute inset-x-0 top-0 h-px animate-shimmer-sweep bg-gradient-to-r from-transparent via-status-tool/70 to-transparent"
            />
          )}
          <div className="font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
            {t("issue.decision.recommendation.label")}
          </div>
          <div
            data-density="decision-routing-badge"
            className={cn(
              "mt-2 inline-flex min-h-7 max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] font-black leading-snug",
              TONE_CLASS[view.tone],
              isParallelRouting && "motion-essential",
            )}
          >
            {isParallelRouting && <RoutingMotion isParallelRouting={isParallelRouting} />}
            {t(view.recommendationKey)}
          </div>
        </div>
        <div className="rounded-lg border border-border-subtle/50 bg-surface-input/35 p-2.5">
          <div className="font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
            {t("issue.decision.batch.label")}
          </div>
          <div className={cn("mt-2 inline-flex min-h-7 max-w-full items-center rounded-md border px-2 py-1 text-[12px] font-black leading-snug", policy.batch_allowed ? TONE_CLASS.parallel : TONE_CLASS.serial)}>
            {t(view.batchKey)}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-border-subtle/50 bg-surface-input/25 p-2.5">
        <div className="mb-2 flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.18em] font-extrabold text-text-muted">
          <Info size={12} className="text-text-muted" />
          {t("issue.decision.signals")}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {view.signalKeys.map((key) => (
            <span
              key={key}
              className="rounded-md border border-border-subtle/60 bg-surface px-2 py-1 text-[11px] font-bold leading-none text-text-secondary"
            >
              {t(key)}
            </span>
          ))}
          {view.moreSignals > 0 && (
            <span className="rounded-md border border-border-subtle/60 bg-surface px-2 py-1 text-[11px] font-bold leading-none text-text-muted">
              {t("issue.decision.moreSignals", { n: view.moreSignals })}
            </span>
          )}
        </div>
      </div>

      <ul className="space-y-1.5 px-1 pb-1">
        {view.guidanceKeys.map((key) => (
          <li key={key} className="grid grid-cols-[14px_1fr] gap-2 text-[12px] leading-snug text-text-secondary">
            <span className="mt-1 size-1.5 rounded-full bg-brand" aria-hidden />
            <span>{t(key)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RoutingMotion({ isParallelRouting }: { isParallelRouting: boolean }) {
  return (
    <AgentThinkingIndicator
      phase={isParallelRouting ? "dispatching" : "thinking"}
      size={12}
      className="shrink-0"
    />
  );
}
