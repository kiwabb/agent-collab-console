import type { DecisionTimelineItem } from "../hooks/useDecisionTimeline";

type TimelineSummaryItem = Pick<DecisionTimelineItem, "kind" | "role" | "status" | "titleKey" | "titleParams">;

export interface TimelineExecutionSummary {
  developmentDispatched: number;
  qaDone: number;
  finalized: boolean;
}

function numberParam(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export function deriveTimelineExecutionSummary(items: TimelineSummaryItem[]): TimelineExecutionSummary {
  let batchDevelopmentDispatched = 0;
  let directEngineerDone = 0;
  let qaDone = 0;
  let finalized = false;

  for (const item of items) {
    if (item.titleKey === "issue.command.title.dispatchBatchCount" && item.status !== "failed") {
      batchDevelopmentDispatched = Math.max(batchDevelopmentDispatched, numberParam(item.titleParams?.count));
    }

    if (item.status !== "done") continue;

    if (item.kind === "dispatch" && item.role === "engineer") {
      directEngineerDone += 1;
    }

    if (item.kind === "dispatch" && item.role === "qa") {
      qaDone += 1;
    }

    if (item.kind === "finalize") {
      finalized = true;
    }
  }

  return {
    developmentDispatched: Math.max(batchDevelopmentDispatched, directEngineerDone),
    qaDone,
    finalized,
  };
}
