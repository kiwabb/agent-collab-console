import type {
  IssueOrchestrationPolicy,
  OrchestrationRecommendation,
} from "@/lib/types";
import type { TranslationKey } from "@/lib/i18n";

export type DecisionExplanationTone = "serial" | "parallel" | "clarify" | "review";

export interface DecisionExplanationView {
  recommendationKey: TranslationKey;
  batchKey: TranslationKey;
  signalKeys: TranslationKey[];
  guidanceKeys: TranslationKey[];
  tone: DecisionExplanationTone;
  moreSignals: number;
}

const MAX_VISIBLE_SIGNALS = 3;

const RECOMMENDATION_KEYS = {
  pm_first: "issue.decision.recommendation.pm_first",
  architect_first: "issue.decision.recommendation.architect_first",
  batch_allowed: "issue.decision.recommendation.batch_allowed",
  single_engineer: "issue.decision.recommendation.single_engineer",
} satisfies Record<OrchestrationRecommendation, TranslationKey>;

const SIGNAL_KEYS: Record<string, TranslationKey> = {
  explicit_parallel: "issue.decision.signal.explicit_parallel",
  independent_slices: "issue.decision.signal.independent_slices",
  trivial: "issue.decision.signal.trivial",
  ambiguous_scope: "issue.decision.signal.ambiguous_scope",
  risk_or_cross_layer: "issue.decision.signal.risk_or_cross_layer",
  default_serial: "issue.decision.signal.default_serial",
};

const GUIDANCE_KEYS = {
  pm_first: [
    "issue.decision.guidance.pm.1",
    "issue.decision.guidance.pm.2",
    "issue.decision.guidance.pm.3",
  ],
  architect_first: [
    "issue.decision.guidance.architect.1",
    "issue.decision.guidance.architect.2",
    "issue.decision.guidance.architect.3",
  ],
  batch_allowed: [
    "issue.decision.guidance.batch.1",
    "issue.decision.guidance.batch.2",
    "issue.decision.guidance.batch.3",
  ],
  single_engineer: [
    "issue.decision.guidance.singleEngineer.1",
    "issue.decision.guidance.singleEngineer.2",
    "issue.decision.guidance.singleEngineer.3",
  ],
} satisfies Record<OrchestrationRecommendation, TranslationKey[]>;

export function deriveDecisionExplanationView(
  policy: IssueOrchestrationPolicy,
): DecisionExplanationView {
  const recommendation = normalizeRecommendation(policy.recommendation);
  const visibleSignals = policy.signals.slice(0, MAX_VISIBLE_SIGNALS);
  return {
    recommendationKey: RECOMMENDATION_KEYS[recommendation],
    batchKey: policy.batch_allowed
      ? "issue.decision.batch.allowed"
      : "issue.decision.batch.notAllowed",
    signalKeys: visibleSignals.map(
      (signal) => SIGNAL_KEYS[signal] ?? "issue.decision.signal.unknown",
    ),
    guidanceKeys: GUIDANCE_KEYS[recommendation],
    tone: deriveTone(recommendation, policy.batch_allowed),
    moreSignals: Math.max(0, policy.signals.length - MAX_VISIBLE_SIGNALS),
  };
}

function normalizeRecommendation(value: string): OrchestrationRecommendation {
  if (
    value === "pm_first" ||
    value === "architect_first" ||
    value === "batch_allowed" ||
    value === "single_engineer"
  ) {
    return value;
  }
  return "single_engineer";
}

function deriveTone(
  recommendation: OrchestrationRecommendation,
  batchAllowed: boolean,
): DecisionExplanationTone {
  if (batchAllowed || recommendation === "batch_allowed") return "parallel";
  if (recommendation === "pm_first") return "clarify";
  if (recommendation === "architect_first") return "review";
  return "serial";
}
