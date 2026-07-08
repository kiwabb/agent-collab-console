"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Download, ExternalLink, RefreshCw } from "lucide-react";
import { getCodexIssueArtifacts } from "@/lib/api/issues";
import type { Artifact, CodexIssue } from "@/lib/types";
import { ArtifactsSplitView } from "@/features/issues/components/ArtifactsSplitView";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { AgentThinkingIndicator } from "@/components/ui/AgentThinkingIndicator";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { useBusEventEffect, busEventMatchers } from "@/hooks/useBusEventEffect";
import { useI18n } from "@/providers/I18nProvider";

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
  const { addToast } = useToast();
  const { t } = useI18n();
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastFetched, setLastFetched] = useState<number | null>(null);
  const inFlight = useRef(false);

  // Summary stats for the toolbar — total bytes across all artifact bodies
  // and a deduplicated set of producer agents.
  const { totalBytes, producers } = useMemo(() => {
    let bytes = 0;
    const set = new Set<string>();
    for (const a of artifacts) {
      const c = typeof a.content === "string" ? a.content : "";
      bytes += c.length;
      const tag = inferProducer(a);
      if (tag) set.add(tag);
    }
    return { totalBytes: bytes, producers: set.size };
  }, [artifacts]);

  const handleCopyEditorCmd = useCallback(async () => {
    const cwd = issue?.git_worktree_path;
    if (!cwd) {
      addToast({ type: "error", title: t("issue.artifacts.noWorktree") });
      return;
    }
    const cmd = `cd "${cwd}" && code .`;
    try {
      await navigator.clipboard.writeText(cmd);
      addToast({
        type: "success",
        title: t("issue.artifacts.copiedCmd"),
        message: cmd,
      });
    } catch {
      addToast({
        type: "error",
        title: t("issue.artifacts.clipboardUnavailable"),
      });
    }
  }, [issue?.git_worktree_path, addToast, t]);

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

  // Event-driven refresh: artifacts get written when a task completes a phase
  // (PM PRD, Architect design, Engineer code, QA report). task_status with
  // terminal status is the right hook.
  useBusEventEffect({
    match: busEventMatchers.all(
      busEventMatchers.issueId(issueId),
      busEventMatchers.typeIn("task_status", "workflow_node_updated"),
    ),
    onEvent: () => {
      void fetchArtifacts("poll");
    },
    throttleMs: 500,
    enabled: active,
  });

  // Fallback poll while in flight, lengthened to 15s now that events do the
  // heavy lifting.
  useEffect(() => {
    if (!active) return;
    if (!issue || !ACTIVE_STATUSES.has(issue.status ?? "")) return;
    const id = window.setInterval(() => void fetchArtifacts("poll"), 15000);
    return () => window.clearInterval(id);
  }, [active, issue, fetchArtifacts]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border-subtle font-mono text-[12px] text-text-muted flex-wrap">
        <div className="flex items-center gap-3.5 flex-wrap">
          <span>
            <b className="text-foreground font-medium">{artifacts.length}</b> artifacts
          </span>
          <span className="text-text-faint">·</span>
          <span>
            {t("issue.artifacts.totalLabel")}{" "}
            <b className="text-foreground font-medium">{fmtSize(totalBytes)}</b>
          </span>
          <span className="text-text-faint">·</span>
          <span>
            <b className="text-foreground font-medium">{producers}</b>{" "}
            {t("issue.artifacts.producersLabel")}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Button
            size="sm"
            variant="outline"
            disabled={isRefreshing || isLoading}
            onClick={() => void fetchArtifacts("refresh")}
            data-density={isRefreshing ? "artifacts-tab-refresh-tool" : "artifacts-tab-refresh"}
            className={cn("h-7 px-2.5 text-[12px]", isRefreshing && "motion-essential")}
          >
            {isRefreshing ? (
              <AgentThinkingIndicator phase="tool" size={11} />
            ) : (
              <RefreshCw size={11} />
            )}
            Refresh
          </Button>
          <a
            href={`/api/codex/issues/${issueId}/artifacts/download`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-border-muted bg-surface-raised text-[12px] text-text-secondary hover:text-foreground hover:bg-surface-input hover:border-border-strong"
            title={t("issue.artifacts.downloadHint")}
          >
            <Download size={11} />
            {t("issue.artifacts.downloadZip")}
          </a>
          <Button
            size="sm"
            variant="outline"
            onClick={() => void handleCopyEditorCmd()}
            disabled={!issue?.git_worktree_path}
            className="h-7 px-2.5 text-[12px]"
            title={
              issue?.git_worktree_path
                ? t("issue.artifacts.copyEditorHint")
                : t("issue.artifacts.noWorktree")
            }
          >
            <ExternalLink size={11} className="mr-1.5" />
            {t("issue.artifacts.openInEditor")}
          </Button>
        </div>
      </div>
      <div className="flex-1 min-h-0 px-4 pb-4 pt-3">
        {!isLoading && artifacts.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <EmptyState
              icon="artifact"
              title="No artifacts yet"
              description="Run a phase in the DAG or Tasks·Runs tab to produce PRD, design, and QA reports."
            />
          </div>
        ) : (
          <ArtifactsSplitView artifacts={artifacts} />
        )}
      </div>
    </div>
  );
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function inferProducer(a: Artifact): string {
  const k = (a.kind || "").toLowerCase();
  if (/(pm|product_manager)/.test(k)) return "pm";
  if (/architect/.test(k)) return "architect";
  if (/engineer/.test(k)) return "engineer";
  if (/qa/.test(k)) return "qa";
  const n = a.name ?? "";
  if (n.startsWith("pm/")) return "pm";
  if (n.startsWith("architect/")) return "architect";
  if (n.startsWith("engineer/")) return "engineer";
  if (n.startsWith("qa/")) return "qa";
  return "";
}
