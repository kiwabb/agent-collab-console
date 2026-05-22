"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FileBox, RefreshCw, ChevronRight, Search } from "lucide-react";

import { getCodexIssueArtifacts, getCodexIssues } from "@/lib/api";
import type { Artifact, CodexIssue } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  EmptyStateAction,
  InteractionEmptyState,
} from "@/components/ui/interaction-empty-state";
import { useToast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { PageFrame } from "@/features/workbench/components/PageFrame";

interface IssueWithArtifacts {
  issue: CodexIssue;
  artifacts: Artifact[];
}

const MAX_SCAN = 25; // cap how many recent issues we scan to keep this fast

function artifactPath(a: Artifact): string {
  return a.name || a.kind || a.id.slice(0, 8);
}

export function ArtifactsHubPage() {
  const router = useRouter();
  const { addToast } = useToast();
  const [rows, setRows] = useState<IssueWithArtifacts[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");

  const load = useCallback(
    async (mode: "initial" | "refresh") => {
      if (mode === "initial") setLoading(true);
      else setRefreshing(true);
      try {
        const issues = await getCodexIssues(null, null);
        const recent = issues.slice(0, MAX_SCAN);
        const results = await Promise.all(
          recent.map(async (issue) => {
            const artifacts = await getCodexIssueArtifacts(issue.id).catch(() => []);
            return { issue, artifacts };
          }),
        );
        setRows(results.filter((r) => r.artifacts.length > 0));
      } catch (err) {
        addToast({
          type: "error",
          title: "Failed to load artifacts",
          message: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [addToast],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        (r.issue.title || "").toLowerCase().includes(q) ||
        r.artifacts.some((a) => artifactPath(a).toLowerCase().includes(q)),
    );
  }, [rows, query]);

  const totalArtifacts = useMemo(
    () => rows.reduce((acc, r) => acc + r.artifacts.length, 0),
    [rows],
  );

  return (
    <PageFrame
      eyebrow="artifacts"
      title="Artifacts"
      description={`${totalArtifacts} files across ${rows.length} ${rows.length === 1 ? "issue" : "issues"} · scanning the latest ${MAX_SCAN} issues`}
      actions={(
        <Button
          size="sm"
          variant="outline"
          disabled={refreshing}
          onClick={() => void load("refresh")}
        >
          <RefreshCw size={12} className={cn("mr-1.5", refreshing && "animate-spin")} />
          Refresh
        </Button>
      )}
      contentClassName="space-y-5"
    >
        <div className="enterprise-card relative max-w-md rounded-2xl p-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by issue title or filename…"
            className="pl-8 bg-surface-input border-border-subtle h-8 text-[13px]"
          />
        </div>

        {loading ? (
          <InteractionEmptyState
            tone="loading"
            title="Loading artifacts"
            description="Scanning recent issues for PRDs, designs, QA reports, and execution outputs."
          />
        ) : filtered.length === 0 ? (
          <InteractionEmptyState
            title={query ? "No artifacts match your search." : "No artifacts produced yet."}
            description={
              query
                ? "Try a different filename, issue title, or clear the search query."
                : "Run an issue through the workflow to produce PRD, design, and QA reports."
            }
            action={
              query ? (
                <EmptyStateAction onClick={() => setQuery("")}>
                  Clear search
                </EmptyStateAction>
              ) : (
                <EmptyStateAction onClick={() => router.push("/")}>
                  Open Inbox
                </EmptyStateAction>
              )
            }
          />
        ) : (
          <ul className="space-y-3">
            {filtered.map(({ issue, artifacts }) => (
              <li
                key={issue.id}
              className="enterprise-card overflow-hidden rounded-2xl hover:border-border-strong transition-colors"
              >
                <button
                  type="button"
                  onClick={() => router.push(`/issues/${issue.id}?tab=artifacts`)}
                  className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-surface-hover transition-colors"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-semibold truncate">
                      {issue.title || issue.id.slice(0, 8)}
                    </div>
                    <div className="text-[11px] text-text-muted">
                      Phase {issue.current_phase ?? "—"} · {artifacts.length}{" "}
                      {artifacts.length === 1 ? "file" : "files"}
                    </div>
                  </div>
                  <ChevronRight size={14} className="text-text-muted shrink-0" />
                </button>
                <ul className="border-t border-border-subtle divide-y divide-border-subtle">
                  {artifacts.slice(0, 6).map((a) => (
                    <li
                      key={a.id}
                      className="px-4 py-2 flex items-center gap-2 text-[12px] text-text-secondary"
                    >
                      <span className="text-text-muted">·</span>
                      <span className="font-mono truncate flex-1">{artifactPath(a)}</span>
                      <span className="uppercase text-[10px] tracking-wider text-text-muted shrink-0">
                        {a.kind}
                      </span>
                    </li>
                  ))}
                  {artifacts.length > 6 && (
                    <li className="px-4 py-2 text-[11px] text-text-muted">
                      + {artifacts.length - 6} more in this issue
                    </li>
                  )}
                </ul>
              </li>
            ))}
          </ul>
        )}
    </PageFrame>
  );
}
