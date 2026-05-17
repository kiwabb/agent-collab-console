"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { getCodexIssueArtifacts } from "@/lib/api";
import type { Artifact, CodexIssue } from "@/lib/types";
import { ArtifactPanel } from "@/features/artifacts/ArtifactPanel";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  issueId: string;
  /** When true, this tab is the active panel — triggers a refetch each time
   * the user navigates back. Without this the artifacts list could stay
   * stale after the orchestration has produced more files. */
  active: boolean;
  /** The parent issue, used to decide whether to live-poll (only while a
   * phase is in flight). */
  issue: CodexIssue | null;
}

const ACTIVE_STATUSES = new Set(["open", "in_progress"]);

export function ArtifactsTab({ issueId, active, issue }: Props) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastFetched, setLastFetched] = useState<number | null>(null);
  const inFlight = useRef(false);

  const fetchArtifacts = useCallback(
    async (mode: "initial" | "refresh" | "poll") => {
      if (inFlight.current) return;
      inFlight.current = true;
      if (mode === "initial") setIsLoading(true);
      if (mode === "refresh") setIsRefreshing(true);
      try {
        const data = await getCodexIssueArtifacts(issueId);
        setArtifacts(data);
        setLastFetched(Date.now());
      } catch {
        if (mode === "initial") setArtifacts([]);
      } finally {
        if (mode === "initial") setIsLoading(false);
        if (mode === "refresh") setIsRefreshing(false);
        inFlight.current = false;
      }
    },
    [issueId],
  );

  // Refetch whenever this tab becomes active (or issueId changes). Without
  // this, the user sees the stale list from when they first opened the page.
  useEffect(() => {
    if (!active) return;
    void fetchArtifacts(lastFetched === null ? "initial" : "refresh");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, issueId]);

  // Live-poll while the issue is still in flight. Cleared as soon as the
  // issue lands in a terminal state.
  useEffect(() => {
    if (!active) return;
    if (!issue || !ACTIVE_STATUSES.has(issue.status ?? "")) return;
    const id = window.setInterval(() => void fetchArtifacts("poll"), 5000);
    return () => window.clearInterval(id);
  }, [active, issue, fetchArtifacts]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-6 pt-4 pb-2">
        <div className="flex items-center gap-2 text-[11px] text-text-muted">
          <span className="font-mono tabular-nums">
            {artifacts.length} {artifacts.length === 1 ? "artifact" : "artifacts"}
          </span>
          {lastFetched && (
            <>
              <span>·</span>
              <span>updated {timeAgo(lastFetched)}</span>
            </>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          disabled={isRefreshing || isLoading}
          onClick={() => void fetchArtifacts("refresh")}
        >
          <RefreshCw size={12} className={cn("mr-1.5", isRefreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>
      <div className="flex-1 min-h-0 px-6 pb-6">
        {!isLoading && artifacts.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <EmptyState
              icon="artifact"
              title="No artifacts yet"
              description="Run a phase in the DAG or Tasks·Runs tab to produce PRD, design, and QA reports."
            />
          </div>
        ) : (
          <ArtifactPanel artifacts={artifacts} isLoading={isLoading} />
        )}
      </div>
    </div>
  );
}

function timeAgo(ts: number): string {
  const delta = Date.now() - ts;
  if (delta < 1500) return "just now";
  if (delta < 60_000) return `${Math.floor(delta / 1000)}s ago`;
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`;
  return `${Math.floor(delta / 3_600_000)}h ago`;
}
